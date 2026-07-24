import ForceGraph3D, {
  type ForceGraphMethods,
  type GraphData,
  type LinkObject,
  type NodeObject,
} from 'react-force-graph-3d';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BoxGeometry,
  CanvasTexture,
  CapsuleGeometry,
  CylinderGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  OctahedronGeometry,
  SphereGeometry,
  Sprite,
  SpriteMaterial,
  TextureLoader,
} from 'three';

export type Position3D = { x: number; y: number; z: number };

export type Graph3DNode = Position3D & {
  id: string;
  label: string;
  nodeType: string;
  shape: string;
  imageUrl: string;
  sharedMapCount: number;
  metric: string;
  color: string;
};

export type Graph3DLink = {
  id: string;
  source: string;
  target: string;
  label: string;
  edgeType: string;
};

type Graph3DViewProps = {
  nodes: Graph3DNode[];
  links: Graph3DLink[];
  selectedNodeId?: string;
  selectedEdgeId?: string;
  invertedBackground: boolean;
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
  onClearSelection: () => void;
  onNodePositionChange: (id: string, position: Position3D) => void;
};

const NODE_COLORS: Record<string, string> = {
  actor: '#eab308',
  process: '#3b82f6',
  condition: '#ef4444',
  news: '#14b8a6',
  data: '#14b8a6',
  source: '#f97316',
  topic: '#22c55e',
  model: '#a855f7',
  component: '#8b5cf6',
  storage: '#94a3b8',
  section: '#10b981',
  task: '#0ea5e9',
  milestone: '#f59e0b',
  result: '#2dd4bf',
  product: '#0f172a',
  technology_block: '#0e7490',
  technology: '#475569',
  program: '#334155',
  program_goal: '#4338ca',
  indicator: '#64748b',
  activity: '#7e22ce',
  project: '#0369a1',
  expected_result: '#15803d',
};
const LINK_COLORS: Record<string, string> = {
  todo: '#ef4444',
  follow: '#60a5fa',
  found: '#60a5fa',
  include: '#c084fc',
  from_source: '#fb923c',
  source: '#fb923c',
  about: '#34d399',
  score: '#34d399',
  contains: '#34d399',
  implements: '#a78bfa',
  develops: '#2dd4bf',
  make: '#4ade80',
  intersects_with: '#fb923c',
  supports: '#f472b6',
  has_block: '#94a3b8',
  has_process: '#38bdf8',
  uses_technology: '#2dd4bf',
  has_goal: '#818cf8',
  has_indicator: '#94a3b8',
  has_activity: '#c084fc',
  has_project: '#38bdf8',
  produces_result: '#4ade80',
};
const BOX_SHAPES = new Set(['component', 'class', 'document']);
const LARGE_NODE_TYPES = new Set(['actor', 'storage', 'model']);
const ANIMATED_EDGE_TYPES = new Set(['todo', 'follow', 'decision', 'found', 'score']);
const TEXTURE_LOADER = new TextureLoader().setCrossOrigin('anonymous');
const IMAGE_TEXTURES = new Map<string, ReturnType<TextureLoader['load']>>();

export default function Graph3DView({
  nodes,
  links,
  selectedNodeId,
  selectedEdgeId,
  invertedBackground,
  onSelectNode,
  onSelectEdge,
  onClearSelection,
  onNodePositionChange,
}: Graph3DViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<ForceGraphMethods<Graph3DNode, Graph3DLink> | undefined>(undefined);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const graphData = useMemo<GraphData<Graph3DNode, Graph3DLink>>(
    () => ({
      nodes: nodes.map((node) => ({
        ...node,
        fx: node.x,
        fy: node.y,
        fz: node.z,
      })),
      links: links.map((link) => ({ ...link })),
    }),
    [links, nodes],
  );

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.max(1, Math.floor(entry.contentRect.width));
      const height = Math.max(1, Math.floor(entry.contentRect.height));
      setSize({ width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => frameGraph(graphRef.current, nodes), 200);
    return () => window.clearTimeout(timer);
  }, [graphData, nodes, size.height, size.width]);

  function focusNode(node: NodeObject<Graph3DNode>) {
    const position = spatialPosition(node);
    const distance = Math.max(90, Math.hypot(position.x, position.y, position.z) * 0.45);
    const length = Math.hypot(position.x, position.y, position.z) || 1;
    const ratio = 1 + distance / length;
    const cameraPosition = length === 1 && position.x === 0 && position.y === 0 && position.z === 0
      ? { x: 0, y: 0, z: distance }
      : {
          x: position.x * ratio,
          y: position.y * ratio,
          z: position.z * ratio,
        };
    graphRef.current?.cameraPosition(
      cameraPosition,
      position,
      500,
    );
    onSelectNode(String(node.id));
  }

  return (
    <div
      className={`graph-3d${invertedBackground ? '' : ' is-light'}`}
      ref={containerRef}
      data-testid="graph-3d"
    >
      <ForceGraph3D<Graph3DNode, Graph3DLink>
        ref={graphRef}
        width={size.width}
        height={size.height}
        graphData={graphData}
        backgroundColor={invertedBackground ? '#111418' : '#f8fafc'}
        controlType="orbit"
        showNavInfo={false}
        enableNodeDrag
        enableNavigationControls
        nodeThreeObject={(node) => createNodeObject(node, String(node.id) === selectedNodeId)}
        nodeLabel={(node) => tooltip(
          node.label,
          `${node.nodeType}${node.metric ? ` · ${node.metric}` : ''}`,
        )}
        nodeVal={(node) => nodeSize(node.nodeType)}
        nodeColor={(node) => nodeColor(
          node.nodeType,
          String(node.id) === selectedNodeId,
          node.sharedMapCount > 1,
          node.color,
        )}
        linkLabel={(link) => tooltip(link.label || link.edgeType, link.edgeType)}
        linkColor={(link) =>
          linkColor(link.edgeType, String(link.id) === selectedEdgeId, invertedBackground)
        }
        linkWidth={(link) => (String(link.id) === selectedEdgeId ? 3.4 : 1.6)}
        linkOpacity={0.78}
        linkDirectionalArrowLength={5}
        linkDirectionalArrowRelPos={0.88}
        linkDirectionalArrowColor={(link) => linkColor(link.edgeType, false, invertedBackground)}
        linkDirectionalParticles={(link) => animatedLink(link.edgeType) ? 2 : 0}
        linkDirectionalParticleWidth={2.2}
        linkDirectionalParticleSpeed={0.006}
        linkDirectionalParticleColor={(link) => linkColor(link.edgeType, false, invertedBackground)}
        onNodeClick={focusNode}
        onNodeDragEnd={(node) => onNodePositionChange(String(node.id), spatialPosition(node))}
        onLinkClick={(link: LinkObject<Graph3DNode, Graph3DLink>) =>
          onSelectEdge(String(link.id))
        }
        onBackgroundClick={onClearSelection}
      />
      <div className="graph-3d-actions">
        <button type="button" onClick={() => frameGraph(graphRef.current, nodes)}>
          Весь граф
        </button>
      </div>
    </div>
  );
}

function frameGraph(
  graph: ForceGraphMethods<Graph3DNode, Graph3DLink> | undefined,
  nodes: Graph3DNode[],
): void {
  if (!graph || nodes.length === 0) {
    return;
  }
  const bounds = nodes.reduce(
    (result, node) => ({
      minX: Math.min(result.minX, node.x),
      maxX: Math.max(result.maxX, node.x),
      minY: Math.min(result.minY, node.y),
      maxY: Math.max(result.maxY, node.y),
      minZ: Math.min(result.minZ, node.z),
      maxZ: Math.max(result.maxZ, node.z),
    }),
    {
      minX: Number.POSITIVE_INFINITY,
      maxX: Number.NEGATIVE_INFINITY,
      minY: Number.POSITIVE_INFINITY,
      maxY: Number.NEGATIVE_INFINITY,
      minZ: Number.POSITIVE_INFINITY,
      maxZ: Number.NEGATIVE_INFINITY,
    },
  );
  const center = {
    x: (bounds.minX + bounds.maxX) / 2,
    y: (bounds.minY + bounds.maxY) / 2,
    z: (bounds.minZ + bounds.maxZ) / 2,
  };
  const span = Math.max(
    bounds.maxX - bounds.minX,
    bounds.maxY - bounds.minY,
    bounds.maxZ - bounds.minZ,
  );
  const distance = Math.max(320, span * 1.2);
  graph.cameraPosition(
    {
      x: center.x + distance * 0.32,
      y: center.y + distance * 0.18,
      z: center.z + distance,
    },
    center,
    450,
  );
}

function createNodeObject(node: NodeObject<Graph3DNode>, selected: boolean): Group {
  const shared = node.sharedMapCount > 1;
  const color = nodeColor(node.nodeType, selected, shared, node.color);
  const material = new MeshStandardMaterial({
    color,
    emissive: selected ? color : shared ? '#ec4899' : '#000000',
    emissiveIntensity: selected ? 0.24 : shared ? 0.12 : 0,
    metalness: node.nodeType === 'storage' ? 0.5 : 0.12,
    roughness: 0.48,
  });
  const size = nodeSize(node.nodeType);
  const group = new Group();
  group.add(new Mesh(nodeGeometry(node.shape, node.nodeType, size), material));
  if (node.imageUrl) {
    const image = imageSprite(node.imageUrl);
    image.position.set(0, size + 25, 0);
    group.add(image);
  }
  const label = labelSprite(
    `${node.label}${node.metric ? ` · ${node.metric}` : ''}`,
    selected,
    shared,
  );
  label.position.set(0, size + 8, 0);
  group.add(label);
  return group;
}

function nodeGeometry(shape: string, nodeType: string, size: number) {
  if (shape === 'diamond' || nodeType === 'condition') {
    return new OctahedronGeometry(size * 1.25, 0);
  }
  if (shape === 'database' || nodeType === 'storage') {
    return new CylinderGeometry(size, size, size * 1.55, 24);
  }
  if (shape === 'actor' || nodeType === 'actor') {
    return new CapsuleGeometry(size * 0.62, size * 1.15, 5, 12);
  }
  if (BOX_SHAPES.has(shape)) {
    return new BoxGeometry(size * 1.7, size * 1.15, size * 0.72);
  }
  return new SphereGeometry(size, 22, 16);
}

function labelSprite(label: string, selected: boolean, shared: boolean): Sprite {
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  canvas.width = 512;
  canvas.height = 96;
  if (context) {
    context.fillStyle = selected
      ? 'rgba(250, 204, 21, 0.96)'
      : shared
        ? 'rgba(251, 207, 232, 0.96)'
        : 'rgba(255, 255, 255, 0.92)';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = '#111827';
    context.font = '600 28px Arial';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(shortLabel(label), canvas.width / 2, canvas.height / 2, canvas.width - 30);
  }
  const texture = new CanvasTexture(canvas);
  const sprite = new Sprite(new SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set(100, 18, 1);
  return sprite;
}

function imageSprite(imageUrl: string): Sprite {
  let texture = IMAGE_TEXTURES.get(imageUrl);
  if (!texture) {
    texture = TEXTURE_LOADER.load(imageUrl, undefined, undefined, () => {
      IMAGE_TEXTURES.delete(imageUrl);
    });
    IMAGE_TEXTURES.set(imageUrl, texture);
  }
  const sprite = new Sprite(
    new SpriteMaterial({ map: texture, transparent: true, depthWrite: false }),
  );
  sprite.scale.set(24, 24, 1);
  return sprite;
}

function nodeColor(
  nodeType: string,
  selected: boolean,
  shared = false,
  customColor = '',
): string {
  if (selected) {
    return '#facc15';
  }
  return customColor || (shared ? '#ec4899' : NODE_COLORS[nodeType] || '#60a5fa');
}

function linkColor(edgeType: string, selected: boolean, invertedBackground: boolean): string {
  if (selected) {
    return '#facc15';
  }
  return LINK_COLORS[edgeType] || (invertedBackground ? '#cbd5e1' : '#475569');
}

function nodeSize(nodeType: string): number {
  return LARGE_NODE_TYPES.has(nodeType) ? 14 : 11;
}

function animatedLink(edgeType: string): boolean {
  return ANIMATED_EDGE_TYPES.has(edgeType);
}

function spatialPosition(node: NodeObject<Graph3DNode>): Position3D {
  return {
    x: finiteCoordinate(node.x),
    y: finiteCoordinate(node.y),
    z: finiteCoordinate(node.z),
  };
}

function finiteCoordinate(value: unknown): number {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number * 100) / 100 : 0;
}

function shortLabel(value: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  return normalized.length > 38 ? `${normalized.slice(0, 37)}…` : normalized;
}

function tooltip(label: string, type: string): string {
  return `<strong>${escapeHtml(label)}</strong><br><span>${escapeHtml(type)}</span>`;
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (character) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[character] || character,
  );
}
