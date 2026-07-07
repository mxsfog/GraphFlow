import {
  Background,
  Controls,
  Edge,
  Handle,
  MarkerType,
  MiniMap,
  Node,
  Position,
  ReactFlow,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { CSSProperties } from 'react';
import { useEffect, useMemo, useState } from 'react';

type Notation = 'flow' | 'use_case' | 'component' | 'class';

type GraphPayload = {
  graph_id: string;
  title?: string;
  notation: Notation;
  nodes: GraphApiNode[];
  edges: GraphApiEdge[];
};

type GraphApiNode = {
  id: string;
  label: string;
  type: string;
  shape: string;
  position: { x: number; y: number };
  style: Record<string, string | number>;
  data: Record<string, unknown>;
};

type GraphApiEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  style: Record<string, string | number>;
  data: Record<string, unknown>;
};

type SearchRunSummary = {
  run_id: string;
  query: string;
  model: string;
  finished_at: string;
  ranked_count: number;
};

type GraphViewerProps = {
  apiBaseUrl: string;
};

type NotationNodeData = {
  label: string;
  shape: string;
  nodeType: string;
  style: Record<string, string | number>;
  raw: Record<string, unknown>;
};

type SystemBoundaryData = {
  label: string;
};

const NOTATIONS: Array<{ value: Notation; label: string }> = [
  { value: 'flow', label: 'Workflow' },
  { value: 'use_case', label: 'UML Use Case' },
  { value: 'component', label: 'Components' },
  { value: 'class', label: 'Classes' },
];

const nodeTypes = {
  notationNode: NotationNode,
  systemBoundary: SystemBoundary,
};

export function GraphViewer({ apiBaseUrl }: GraphViewerProps) {
  const [notation, setNotation] = useState<Notation>('flow');
  const [runs, setRuns] = useState<SearchRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [selected, setSelected] = useState<NotationNodeData | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    void loadJson<{ runs: SearchRunSummary[] }>(
      `${apiBaseUrl}/api/search-runs`,
      controller.signal,
    )
      .then(({ runs }) => {
        setRuns(runs);
        setSelectedRunId((current) => current || defaultRunId(runs));
      })
      .catch((error: Error) => {
        if (error.name !== 'AbortError') {
          setError(error.message);
        }
      });
    return () => controller.abort();
  }, [apiBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    const graphUrl = selectedRunId
      ? `${apiBaseUrl}/api/graph/run/${encodeURIComponent(selectedRunId)}?notation=${notation}&limit=6`
      : `${apiBaseUrl}/api/graph/latest-run?notation=${notation}&limit=6`;
    void loadJson<GraphPayload>(graphUrl, controller.signal)
      .then(setPayload)
      .catch((error: Error) => {
        if (error.name !== 'AbortError') {
          setError(error.message);
        }
      });
    return () => controller.abort();
  }, [apiBaseUrl, notation, selectedRunId]);

  const { nodes, edges } = useMemo(() => toReactFlow(payload), [payload]);

  return (
    <ReactFlowProvider>
      <div className="graph-page">
        <header className="graph-toolbar">
          <div>
            <div className="toolbar-title-row">
              <h1>{payload?.title || 'Последний запуск пайплайна'}</h1>
            </div>
            <p>
              {notationLabel(notation)} / {payload?.nodes.length ?? 0} nodes /{' '}
              {payload?.edges.length ?? 0} edges
            </p>
          </div>
          <div className="toolbar-controls">
            <select
              value={selectedRunId}
              onChange={(event) => setSelectedRunId(event.target.value)}
            >
              {runs.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {runOptionLabel(run)}
                </option>
              ))}
            </select>
            <select
              value={notation}
              onChange={(event) => setNotation(event.target.value as Notation)}
            >
              {NOTATIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
        </header>

        {error ? <div className="graph-error">{error}</div> : null}

        <main className="graph-layout">
          <section className="graph-canvas" aria-label="Интерактивный граф">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.18 }}
              minZoom={0.2}
              maxZoom={2}
              onNodeClick={(_, node) => setSelected(node.data as NotationNodeData)}
              proOptions={{ hideAttribution: true }}
            >
              <Background />
              <Controls />
              <MiniMap pannable zoomable />
            </ReactFlow>
          </section>

          <aside className="graph-inspector">
            <h2>Выбранный узел</h2>
            {selected ? (
              <>
                <strong>{selected.label}</strong>
                <dl>
                  <dt>type</dt>
                  <dd>{selected.nodeType}</dd>
                  <dt>shape</dt>
                  <dd>{selected.shape}</dd>
                </dl>
                <pre>{JSON.stringify(selected.raw, null, 2)}</pre>
              </>
            ) : (
              <p>Выберите узел на графе.</p>
            )}
          </aside>
        </main>
      </div>
    </ReactFlowProvider>
  );
}

async function loadJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Graph API вернул HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function toReactFlow(payload: GraphPayload | null): { nodes: Node[]; edges: Edge[] } {
  if (!payload) {
    return { nodes: [], edges: [] };
  }
  const graphNodes: Node[] = payload.nodes.map((node) => ({
    id: node.id,
    type: 'notationNode',
    position: node.position,
    data: {
      label: node.label,
      shape: node.shape,
      nodeType: node.type,
      style: node.style,
      raw: node.data,
    } satisfies NotationNodeData,
    draggable: true,
    zIndex: 2,
  }));

  if (payload.notation === 'use_case') {
    graphNodes.unshift({
      id: '__system_boundary',
      type: 'systemBoundary',
      position: { x: -80, y: -120 },
      data: { label: 'Система поиска и анализа новостей' } satisfies SystemBoundaryData,
      draggable: false,
      selectable: false,
      zIndex: 0,
      style: { width: 1580, height: 460 },
    });
  }

  return {
    nodes: graphNodes,
    edges: payload.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      type: 'smoothstep',
      animated: edge.type === 'decision',
      style: edgeStyle(edge),
      sourceHandle: sourceHandle(edge),
      targetHandle: targetHandle(edge),
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: String(edge.style.stroke || '#475569'),
        width: 22,
        height: 22,
      },
      labelBgPadding: [8, 4],
      labelBgBorderRadius: 4,
      labelBgStyle: { fill: '#ffffff', fillOpacity: 0.92 },
      labelStyle: { fill: '#334155', fontSize: 12, fontWeight: 600 },
    })),
  };
}

function NotationNode({ data }: { data: NotationNodeData }) {
  const nodeClass = `notation-node shape-${data.shape}`;
  const className = data.shape === 'diamond' ? `${nodeClass} has-rotated-content` : nodeClass;
  const meta = typeof data.raw.class === 'string' ? data.raw.class : data.nodeType;

  return (
    <div className={className} style={nodeInlineStyle(data.style)}>
      <NodeHandles />
      {data.shape === 'actor' ? <ActorNode label={data.label} /> : null}
      {data.shape !== 'actor' ? (
        <div className="node-content">
          <div className="node-label">{data.label}</div>
          {data.shape !== 'class' ? <div className="node-meta">{meta}</div> : null}
          {data.shape === 'class' ? <ClassSections raw={data.raw} /> : null}
        </div>
      ) : null}
      {data.shape === 'component' ? <span className="component-mark" /> : null}
    </div>
  );
}

function NodeHandles() {
  return (
    <>
      <Handle
        id="left-target"
        className="node-handle node-handle-target"
        type="target"
        position={Position.Left}
      />
      <Handle
        id="right-source"
        className="node-handle node-handle-source"
        type="source"
        position={Position.Right}
      />
      <Handle
        id="top-target"
        className="node-handle node-handle-top"
        type="target"
        position={Position.Top}
      />
      <Handle
        id="top-source"
        className="node-handle node-handle-top"
        type="source"
        position={Position.Top}
      />
      <Handle
        id="bottom-target"
        className="node-handle node-handle-bottom"
        type="target"
        position={Position.Bottom}
      />
      <Handle
        id="bottom-source"
        className="node-handle node-handle-bottom"
        type="source"
        position={Position.Bottom}
      />
    </>
  );
}

function ActorNode({ label }: { label: string }) {
  return (
    <div className="actor-figure">
      <span className="actor-head" />
      <span className="actor-body" />
      <span className="actor-arms" />
      <span className="actor-legs" />
      <div className="node-label">{label}</div>
    </div>
  );
}

function ClassSections({ raw }: { raw: Record<string, unknown> }) {
  const explicitAttributes = Array.isArray(raw.attributes) ? raw.attributes.map(String) : [];
  const methods = Array.isArray(raw.methods) ? raw.methods.map(String) : [];
  const fallbackAttributes = Object.entries(raw)
    .filter(([key]) => key !== 'attributes' && key !== 'methods')
    .map(([key, value]) => `${key}: ${String(value)}`);
  const attributes = explicitAttributes.length > 0 ? explicitAttributes : fallbackAttributes;
  return (
    <>
      <div className="class-section">
        {attributes.map((attribute) => (
          <span key={attribute}>{attribute}</span>
        ))}
      </div>
      <div className="class-section">
        {methods.map((method) => (
          <span key={method}>{method}</span>
        ))}
      </div>
    </>
  );
}

function nodeInlineStyle(style: Record<string, string | number>): CSSProperties {
  return {
    background: String(style.background || '#ffffff'),
    borderColor: String(style.borderColor || '#475569'),
    borderWidth: style.borderWidth || 2,
  };
}

function edgeStyle(edge: GraphApiEdge) {
  const stroke = String(edge.style.stroke || '#334155');
  const width = Number(edge.style.strokeWidth || 2);
  return {
    ...edge.style,
    stroke,
    strokeWidth: Math.max(width + 1.4, 3.2),
  };
}

function sourceHandle(edge: GraphApiEdge): string {
  if (edge.type === 'saved_to' || edge.type === 'exported_to') {
    return 'bottom-source';
  }
  if (edge.type === 'about') {
    return 'bottom-source';
  }
  return 'right-source';
}

function targetHandle(edge: GraphApiEdge): string {
  if (edge.type === 'score') {
    return 'bottom-target';
  }
  if (edge.type === 'about' || edge.type === 'saved_to' || edge.type === 'exported_to') {
    return 'top-target';
  }
  return 'left-target';
}

function SystemBoundary({ data }: { data: SystemBoundaryData }) {
  return (
    <div className="system-boundary">
      <span>{data.label}</span>
    </div>
  );
}

function notationLabel(notation: Notation): string {
  const labels: Record<Notation, string> = {
    flow: 'Workflow',
    use_case: 'UML Use Case',
    component: 'Component Diagram',
    class: 'Class Diagram',
  };
  return labels[notation];
}

function runOptionLabel(run: SearchRunSummary): string {
  const date = run.finished_at ? ` / ${run.finished_at}` : '';
  return `${run.query} / ${run.ranked_count} links${date}`;
}

function defaultRunId(runs: SearchRunSummary[]): string {
  return runs.find((run) => run.ranked_count >= 4)?.run_id || runs[0]?.run_id || '';
}
