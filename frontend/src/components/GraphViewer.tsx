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
  ReactFlowInstance,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { CSSProperties, FormEvent } from 'react';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AuthError,
  deleteGraphView,
  deleteGraphGroup,
  deleteGraphTemplate,
  encodeBasicAuth,
  loadGraphViews,
  loadJson,
  loadGraphGroups,
  loadNodeOccurrences,
  loadGraphTemplate,
  loadGraphTemplates,
  saveAnnotation,
  saveAnnotationsBatch,
  saveCustomGraphDefinition,
  saveGraphGroup,
  saveGraphTemplate,
  saveGraphView,
  type GraphGroupRecord,
  type GraphTemplateDefinition,
  type GraphTemplateEdge,
  type GraphTemplateGroup,
  type GraphTemplateNode,
  type GraphTemplateRecord,
  type GraphViewRecord,
  type NodeOccurrence,
} from '../graphApiClient';
import {
  downloadGraphPresentation,
  downloadGraphSvg,
  type GraphExport,
} from '../graphExport';
import { arrangeGraphNodes, parseCreatedAt, type LayoutMode } from '../graphLayout';
import {
  attributeOptions as buildAttributeOptions,
  branchRoots,
  canonicalNodeLabel,
  EMPTY_ATTRIBUTE_FILTERS,
  hiddenBranchNodeIds,
  hierarchyLevels,
  matchesAttributeFilters,
  metricValue,
  nodeMetadata,
  readinessPresentation,
  type AttributeFilters,
  type AttributeOptions,
  type MetricMode,
  type NodeMetadata,
  type SemanticNode,
} from '../graphSemantics';
import {
  descendantNodeIds,
  groupIdFromNode,
  groupNodeId,
  projectWorkspace,
  recursiveGroupNodeIds,
  type GroupProjection,
} from '../graphWorkspace';
import type { Graph3DLink, Graph3DNode, Position3D } from './Graph3DView';
import { GraphLegend, type LegendEntry } from './GraphLegend';
import { ReadableEdge, type EdgeRoutingData } from './ReadableEdge';
import { VisualizationTools } from './VisualizationTools';

const Graph3DView = lazy(() => import('./Graph3DView'));

type Notation = 'flow' | 'use_case' | 'component' | 'class';
type ViewMode = '2d' | '3d';
type Selection = { kind: 'node' | 'edge'; id: string } | null;
type AnnotationRequest = {
  graphId: string;
  notation: Notation;
  elementId: string;
  elementKind: 'node' | 'edge';
  payload: Record<string, unknown>;
};

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

type EditableProperty = {
  id: string;
  key: string;
  value: string;
};

type BaseNodeState = {
  label: string;
  shape: string;
  imageUrl: string;
  createdAt: string;
  endedAt: string;
  position: { x: number; y: number };
  position3d: Position3D;
  properties: EditableProperty[];
};

type BaseEdgeState = {
  label: string;
  edgeType: string;
  properties: EditableProperty[];
};

type NotationNodeData = {
  label: string;
  shape: string;
  nodeType: string;
  imageUrl: string;
  createdAt: string;
  endedAt: string;
  position3d: Position3D;
  properties: EditableProperty[];
  annotationRevision: number;
  base: BaseNodeState;
  style: Record<string, string | number>;
  raw: Record<string, unknown>;
  hierarchyLevel?: number;
  branchCollapsed?: boolean;
  hasBranch?: boolean;
  sharedMapCount?: number;
  metricMode?: MetricMode;
  metricValue?: string;
  onToggleBranch?: () => void;
};

type EditableEdgeData = EdgeRoutingData & {
  label: string;
  edgeType: string;
  properties: EditableProperty[];
  annotationRevision: number;
  base: BaseEdgeState;
  raw: Record<string, unknown>;
  sourceEdgeIds?: string[];
  aggregateCount?: number;
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

const SHAPES = [
  'rounded_rectangle',
  'document',
  'diamond',
  'ellipse',
  'circle',
  'actor',
  'component',
  'class',
  'database',
];

const EDGE_TYPES = [
  'request',
  'found',
  'score',
  'from_source',
  'about',
  'analyzed_by',
  'saved_to',
  'exported_to',
  'todo',
  'follow',
  'include',
  'properties',
  'decision',
  'candidate',
  'source',
  'contains',
  'reference',
  'implements',
  'develops',
  'make',
  'intersects_with',
  'supports',
  'has_block',
  'has_process',
  'uses_technology',
  'has_goal',
  'has_indicator',
  'has_activity',
  'has_project',
  'produces_result',
];
const EDGE_TYPE_STYLES: Record<string, CSSProperties> = {
  todo: { stroke: '#dc2626', strokeWidth: 2.4, strokeDasharray: '7 5' },
  follow: { stroke: '#2563eb', strokeWidth: 2.4 },
  include: { stroke: '#475569', strokeWidth: 2.1, strokeDasharray: '6 4' },
  properties: { stroke: '#0f766e', strokeWidth: 2.1, strokeDasharray: '3 4' },
  implements: { stroke: '#7c3aed', strokeWidth: 2.2 },
  develops: { stroke: '#0f766e', strokeWidth: 2.2 },
  make: { stroke: '#15803d', strokeWidth: 2.3 },
  intersects_with: { stroke: '#c2410c', strokeWidth: 2.2, strokeDasharray: '6 4' },
  supports: { stroke: '#be185d', strokeWidth: 2.4 },
  has_block: { stroke: '#334155', strokeWidth: 2.2 },
  has_process: { stroke: '#0369a1', strokeWidth: 2.1 },
  uses_technology: { stroke: '#0f766e', strokeWidth: 2.1 },
  has_goal: { stroke: '#4338ca', strokeWidth: 2.2 },
  has_indicator: { stroke: '#64748b', strokeWidth: 2.0 },
  has_activity: { stroke: '#7c3aed', strokeWidth: 2.1 },
  has_project: { stroke: '#0369a1', strokeWidth: 2.1 },
  produces_result: { stroke: '#15803d', strokeWidth: 2.2 },
  decision: { stroke: '#ea580c', strokeWidth: 2.4 },
  request: { stroke: '#2563eb', strokeWidth: 2.2 },
  found: { stroke: '#0891b2', strokeWidth: 2.2 },
  from_source: { stroke: '#d97706', strokeWidth: 2.2 },
  source: { stroke: '#d97706', strokeWidth: 2.2 },
  about: { stroke: '#059669', strokeWidth: 2.2 },
  score: { stroke: '#7c3aed', strokeWidth: 2.2 },
  contains: { stroke: '#059669', strokeWidth: 2.2 },
  analyzed_by: { stroke: '#7c3aed', strokeWidth: 2.2 },
  saved_to: { stroke: '#64748b', strokeWidth: 2.2 },
  exported_to: { stroke: '#64748b', strokeWidth: 2.2, strokeDasharray: '6 4' },
};
const DEFAULT_EDGE_TYPE_STYLE: CSSProperties = { stroke: '#64748b', strokeWidth: 2.1 };
const ANIMATED_EDGE_TYPES = new Set<string>();
const CHILD_EDGE_TYPES = new Set([
  'contains',
  'include',
  'properties',
  'has_block',
  'has_process',
  'uses_technology',
  'has_goal',
  'has_indicator',
  'has_activity',
  'has_project',
  'produces_result',
]);
const NODE_TYPE_LEGEND_COLORS: Record<string, string> = {
  product: '#0f172a',
  technology_block: '#0e7490',
  process: '#2563eb',
  technology: '#475569',
  program: '#334155',
  program_goal: '#4338ca',
  indicator: '#64748b',
  activity: '#7e22ce',
  project: '#0369a1',
  expected_result: '#15803d',
};

const nodeTypes = {
  notationNode: NotationNode,
  systemBoundary: SystemBoundary,
  graphGroup: GraphGroupNode,
};
const flowEdgeTypes = { readable: ReadableEdge };

export function GraphViewer({ apiBaseUrl }: GraphViewerProps) {
  const [authToken, setAuthToken] = useState('');
  const [authUser, setAuthUser] = useState('');
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [notation, setNotation] = useState<Notation>('flow');
  const [viewMode, setViewMode] = useState<ViewMode>('2d');
  const [invertedBackground, setInvertedBackground] = useState(
    () => window.localStorage.getItem('graphflow-background') !== 'light',
  );
  const [runs, setRuns] = useState<SearchRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [selected, setSelected] = useState<Selection>(null);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState('');
  const [hiddenNodeTypes, setHiddenNodeTypes] = useState<string[]>([]);
  const [hiddenEdgeTypes, setHiddenEdgeTypes] = useState<string[]>([]);
  const [hiddenLevels, setHiddenLevels] = useState<number[]>([]);
  const [collapsedBranches, setCollapsedBranches] = useState<string[]>([]);
  const [attributeFilters, setAttributeFilters] = useState<AttributeFilters>(
    EMPTY_ATTRIBUTE_FILTERS,
  );
  const [metricMode, setMetricMode] = useState<MetricMode>('planned');
  const [graphRefresh, setGraphRefresh] = useState(0);
  const [groups, setGroups] = useState<GraphGroupRecord[]>([]);
  const [templates, setTemplates] = useState<GraphTemplateRecord[]>([]);
  const [views, setViews] = useState<GraphViewRecord[]>([]);
  const [occurrences, setOccurrences] = useState<NodeOccurrence[]>([]);
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [groupRefresh, setGroupRefresh] = useState(0);
  const [templateRefresh, setTemplateRefresh] = useState(0);
  const [viewRefresh, setViewRefresh] = useState(0);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance<Node<NotationNodeData>, Edge<EditableEdgeData>> | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<NotationNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<EditableEdgeData>>([]);
  const graphRequestGeneration = useRef(0);
  const saveTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const saveQueues = useRef(new Map<string, Promise<void>>());
  const latestSaveRequests = useRef(new Map<string, AnnotationRequest>());
  const annotationRevisions = useRef(new Map<string, number>());
  const pendingSaves = useRef(0);
  const pendingViewport = useRef<{ x: number; y: number; zoom: number } | null>(null);

  const selectedNode = useMemo(
    () => (selected?.kind === 'node' ? nodes.find((node) => node.id === selected.id) : undefined),
    [nodes, selected],
  );
  const selectedEdge = useMemo(
    () => (selected?.kind === 'edge' ? edges.find((edge) => edge.id === selected.id) : undefined),
    [edges, selected],
  );
  const nodeTypeOptions = useMemo(() => uniqueValues(nodes.map((node) => node.data.nodeType)), [nodes]);
  const edgeTypeOptions = useMemo(
    () => uniqueValues(edges.map((edge) => edgeData(edge).edgeType)),
    [edges],
  );
  const selectedNodeIds = useMemo(
    () => nodes.filter((node) => node.selected && !node.id.startsWith('__')).map((node) => node.id),
    [nodes],
  );
  const semanticNodes = useMemo(() => nodes
    .filter((node) => !node.id.startsWith('__'))
    .map(toSemanticNode), [nodes]);
  const semanticById = useMemo(
    () => new Map(semanticNodes.map((node) => [node.id, node])),
    [semanticNodes],
  );
  const metadataOptions = useMemo(() => buildAttributeOptions(semanticNodes), [semanticNodes]);
  const nodeLevels = useMemo(
    () => hierarchyLevels(
      semanticNodes,
      edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        type: edgeData(edge).edgeType,
      })),
    ),
    [edges, semanticNodes],
  );
  const levelOptions = useMemo(() => {
    const counts = new Map<number, number>();
    nodeLevels.forEach((level) => counts.set(level, (counts.get(level) || 0) + 1));
    return [...counts.entries()]
      .sort(([left], [right]) => left - right)
      .map(([level, count]) => ({ level, count }));
  }, [nodeLevels]);
  const branchRootIds = useMemo(
    () => branchRoots(edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      type: edgeData(edge).edgeType,
    }))),
    [edges],
  );
  const branchHiddenNodeIds = useMemo(
    () => hiddenBranchNodeIds(
      new Set(collapsedBranches),
      edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        type: edgeData(edge).edgeType,
      })),
    ),
    [collapsedBranches, edges],
  );
  const occurrencesByKey = useMemo(
    () => new Map(occurrences.map((item) => [item.key, item])),
    [occurrences],
  );
  const filteredNodes = useMemo(
    () => nodes.filter((node) => {
      if (node.id.startsWith('__')) {
        return true;
      }
      const semantic = semanticById.get(node.id);
      const level = nodeLevels.get(node.id) || 0;
      return (
        !hiddenNodeTypes.includes(node.data.nodeType)
        && !hiddenLevels.includes(level)
        && !branchHiddenNodeIds.has(node.id)
        && Boolean(semantic && matchesAttributeFilters(semantic, attributeFilters))
      );
    }),
    [
      attributeFilters,
      branchHiddenNodeIds,
      hiddenLevels,
      hiddenNodeTypes,
      nodeLevels,
      nodes,
      semanticById,
    ],
  );
  const filteredEdges = useMemo(() => {
    const visibleNodeIds = new Set(filteredNodes.map((node) => node.id));
    return edges.filter((edge) => {
      const type = edgeData(edge).edgeType;
      return (
        visibleNodeIds.has(edge.source) &&
        visibleNodeIds.has(edge.target) &&
        !hiddenEdgeTypes.includes(type)
      );
    });
  }, [edges, filteredNodes, hiddenEdgeTypes]);
  const workspaceProjection = useMemo(
    () => projectWorkspace(
      filteredNodes
        .filter((node) => !node.id.startsWith('__'))
        .map((node) => ({
          id: node.id,
          position: node.position,
          width: node.measured?.width,
          height: node.measured?.height,
        })),
      filteredEdges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: edgeData(edge).edgeType,
        label: edgeData(edge).label,
      })),
      groups,
    ),
    [filteredEdges, filteredNodes, groups],
  );
  const visibleNodes = useMemo(() => {
    const graphNodes = filteredNodes.filter(
      (node) => !workspaceProjection.hiddenNodeIds.has(node.id),
    );
    return [
      ...workspaceProjection.groups.map(groupProjectionNode),
      ...graphNodes.map((node) => {
        const semantic = semanticById.get(node.id);
        const metadata = semantic ? nodeMetadata(semantic) : null;
        const occurrence = occurrencesByKey.get(canonicalNodeLabel(node.data.label));
        return {
          ...node,
          data: {
            ...node.data,
            hierarchyLevel: nodeLevels.get(node.id) || 0,
            hasBranch: branchRootIds.has(node.id),
            branchCollapsed: collapsedBranches.includes(node.id),
            sharedMapCount: occurrence?.map_count || 1,
            metricMode,
            metricValue: metadata ? metricValue(metadata, metricMode) : '',
            onToggleBranch: () => toggleBranch(node.id),
          },
        };
      }),
    ];
  }, [
    branchRootIds,
    collapsedBranches,
    filteredNodes,
    metricMode,
    nodeLevels,
    occurrencesByKey,
    semanticById,
    workspaceProjection,
  ]);
  const visibleEdges = useMemo(() => {
    const edgesById = new Map(filteredEdges.map((edge) => [edge.id, edge]));
    const projected = workspaceProjection.edges.flatMap((edge) => {
      const source = edgesById.get(edge.sourceEdgeIds[0]);
      if (!source) {
        return [];
      }
      if (edge.id === source.id && edge.count === 1) {
        return [source];
      }
      const data = edgeData(source);
      const label = edge.count > 1 ? `${data.edgeType} · ${edge.count}` : data.label;
      return [withEdgePresentation(
        {
          ...source,
          id: edge.id,
          source: edge.source,
          target: edge.target,
          selected: false,
        },
        {
          ...data,
          label,
          showLabel: true,
          sourceEdgeIds: edge.sourceEdgeIds,
          aggregateCount: edge.count,
        },
      )];
    });
    return routeFlowEdges(projected, visibleNodes);
  }, [filteredEdges, visibleNodes, workspaceProjection.edges]);
  const graph3dNodes = useMemo<Graph3DNode[]>(
    () => visibleNodes
      .filter((node) => (
        node.id !== '__system_boundary'
        && (!groupIdFromNode(node.id) || Boolean(node.data.raw.collapsed))
      ))
      .map((node) => ({
        id: node.id,
        label: node.data.label,
        nodeType: node.data.nodeType,
        shape: node.data.shape,
        imageUrl: node.data.imageUrl,
        sharedMapCount: node.data.sharedMapCount || 1,
        metric: node.data.metricValue || '',
        color: String(effectiveNodeStyle(node.data).borderColor || '#64748b'),
        ...node.data.position3d,
      })),
    [visibleNodes],
  );
  const graph3dLinks = useMemo<Graph3DLink[]>(
    () => visibleEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edgeData(edge).label,
      edgeType: edgeData(edge).edgeType,
    })),
    [visibleEdges],
  );
  const nodeLegendEntries = useMemo<LegendEntry[]>(() => uniqueByType(
    visibleNodes
      .filter((node) => !node.id.startsWith('__'))
      .map((node) => ({
        type: node.data.nodeType,
        color: NODE_TYPE_LEGEND_COLORS[node.data.nodeType]
          || String(node.data.style.borderColor || node.data.style.background || '#64748b'),
      })),
  ), [visibleNodes]);
  const edgeLegendEntries = useMemo<LegendEntry[]>(() => uniqueByType(
    visibleEdges.map((edge) => {
      const style = edgeTypeStyle(edgeData(edge).edgeType);
      return {
        type: edgeData(edge).edgeType,
        color: String(style.stroke || '#64748b'),
        dashed: Boolean(style.strokeDasharray),
      };
    }),
  ), [visibleEdges]);
  const statusLegendEntries = useMemo<LegendEntry[]>(() => uniqueByType(
    visibleNodes.flatMap((node) => {
      const presentation = readinessPresentation(editablePropertyValue(node.data.properties, 'status'));
      return presentation
        ? [{ type: presentation.label, color: presentation.background }]
        : [];
    }),
  ), [visibleNodes]);

  useEffect(() => {
    window.localStorage.setItem('graphflow-background', invertedBackground ? 'dark' : 'light');
  }, [invertedBackground]);

  useEffect(() => {
    if (selected?.kind === 'node' && !visibleNodes.some((node) => node.id === selected.id)) {
      setSelected(null);
    }
    if (
      selected?.kind === 'edge'
      && !visibleEdges.some((edge) => (
        edge.id === selected.id || edgeData(edge).sourceEdgeIds?.includes(selected.id)
      ))
    ) {
      setSelected(null);
    }
  }, [selected, visibleEdges, visibleNodes]);

  useEffect(() => {
    if (!authToken) {
      return;
    }
    const controller = new AbortController();
    void loadJson<{ runs: SearchRunSummary[] }>(
      `${apiBaseUrl}/api/search-runs`,
      controller.signal,
      authToken,
    )
      .then(({ runs }) => {
        setRuns(runs);
        setSelectedRunId((current) => current || defaultRunId(runs));
      })
      .catch((requestError: Error) => handleRequestError(requestError, setAuthToken, setError));
    return () => controller.abort();
  }, [apiBaseUrl, authToken]);

  useEffect(() => {
    if (!authToken) {
      return;
    }
    const generation = ++graphRequestGeneration.current;
    const controller = new AbortController();
    setError('');
    setIsLoading(true);
    setPayload(null);
    setSelected(null);
    const graphUrl = selectedRunId
      ? `${apiBaseUrl}/api/graph/run/${encodeURIComponent(selectedRunId)}?notation=${notation}&limit=6`
      : `${apiBaseUrl}/api/graph/latest-run?notation=${notation}&limit=6`;
    void loadJson<GraphPayload>(graphUrl, controller.signal, authToken)
      .then((nextPayload) => {
        if (generation === graphRequestGeneration.current) {
          setPayload(nextPayload);
        }
      })
      .catch((requestError: Error) => {
        if (generation === graphRequestGeneration.current) {
          handleRequestError(requestError, setAuthToken, setError);
        }
      })
      .finally(() => {
        if (generation === graphRequestGeneration.current) {
          setIsLoading(false);
        }
      });
    return () => controller.abort();
  }, [apiBaseUrl, authToken, graphRefresh, notation, selectedRunId]);

  useEffect(() => {
    if (!authToken || !payload?.graph_id) {
      setGroups([]);
      return;
    }
    const controller = new AbortController();
    void loadGraphGroups(
      apiBaseUrl,
      authToken,
      payload.graph_id,
      notation,
      controller.signal,
    )
      .then(({ groups: loadedGroups }) => {
        setGroups(loadedGroups);
        setSelectedGroupIds((current) =>
          current.filter((id) => loadedGroups.some((group) => group.group_id === id)),
        );
      })
      .catch((requestError: Error) => handleRequestError(requestError, setAuthToken, setError));
    return () => controller.abort();
  }, [apiBaseUrl, authToken, groupRefresh, notation, payload?.graph_id]);

  useEffect(() => {
    if (!authToken) {
      setTemplates([]);
      return;
    }
    const controller = new AbortController();
    void loadGraphTemplates(apiBaseUrl, authToken, controller.signal)
      .then(({ templates: loadedTemplates }) => setTemplates(loadedTemplates))
      .catch((requestError: Error) => handleRequestError(requestError, setAuthToken, setError));
    return () => controller.abort();
  }, [apiBaseUrl, authToken, templateRefresh]);

  useEffect(() => {
    if (!authToken) {
      setOccurrences([]);
      return;
    }
    const controller = new AbortController();
    void loadNodeOccurrences(apiBaseUrl, authToken, notation, controller.signal)
      .then(({ occurrences: loadedOccurrences }) => setOccurrences(loadedOccurrences))
      .catch((requestError: Error) => handleRequestError(requestError, setAuthToken, setError));
    return () => controller.abort();
  }, [apiBaseUrl, authToken, notation]);

  useEffect(() => {
    if (!authToken || !payload?.graph_id.startsWith('run:') && !payload?.graph_id.startsWith('graph:')) {
      setViews([]);
      return;
    }
    const controller = new AbortController();
    void loadGraphViews(apiBaseUrl, authToken, payload.graph_id, controller.signal)
      .then(({ views: loadedViews }) => setViews(loadedViews))
      .catch((requestError: Error) => handleRequestError(requestError, setAuthToken, setError));
    return () => controller.abort();
  }, [apiBaseUrl, authToken, payload?.graph_id, viewRefresh]);

  useEffect(() => {
    const graph = toReactFlow(payload);
    setNodes(graph.nodes);
    setEdges(graph.edges);
    setSelected(null);
    setSaveStatus('');
    setSelectedGroupIds([]);
    for (const timer of saveTimers.current.values()) {
      clearTimeout(timer);
    }
    saveTimers.current.clear();
    latestSaveRequests.current.clear();
    saveQueues.current.clear();
    annotationRevisions.current.clear();
    for (const node of graph.nodes) {
      annotationRevisions.current.set(
        annotationKey('node', node.id, notation),
        node.data.annotationRevision,
      );
    }
    for (const edge of graph.edges) {
      annotationRevisions.current.set(
        annotationKey('edge', edge.id, notation),
        edgeData(edge).annotationRevision,
      );
    }
  }, [notation, payload, setEdges, setNodes]);

  useEffect(() => {
    const viewport = pendingViewport.current;
    if (!viewport || !flowInstance || isLoading || viewMode !== '2d' || nodes.length === 0) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      void flowInstance.setViewport(viewport, { duration: 250 });
      pendingViewport.current = null;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [flowInstance, isLoading, nodes, viewMode]);

  const enqueueAnnotation = useCallback(
    (request: AnnotationRequest) => {
      const key = annotationKey(request.elementKind, request.elementId, request.notation);
      const previous = saveQueues.current.get(key) || Promise.resolve();
      pendingSaves.current += 1;
      setSaveStatus('Сохранение...');
      const current = previous
        .catch(() => undefined)
        .then(async () => {
          const response = await saveAnnotation(apiBaseUrl, authToken, {
            graph_id: request.graphId,
            notation: request.notation,
            element_id: request.elementId,
            element_kind: request.elementKind,
            revision: annotationRevisions.current.get(key) || 0,
            payload: request.payload,
          });
          annotationRevisions.current.set(key, response.revision);
          setError('');
        })
        .catch((requestError: Error) =>
          handleRequestError(requestError, setAuthToken, setError, setSaveStatus),
        )
        .finally(() => {
          pendingSaves.current = Math.max(0, pendingSaves.current - 1);
          if (pendingSaves.current === 0) {
            setSaveStatus('Сохранено');
          }
          if (saveQueues.current.get(key) === current) {
            saveQueues.current.delete(key);
          }
        });
      saveQueues.current.set(key, current);
    },
    [apiBaseUrl, authToken],
  );

  const scheduleAnnotation = useCallback(
    (request: AnnotationRequest, immediate = false) => {
      const key = annotationKey(request.elementKind, request.elementId, request.notation);
      latestSaveRequests.current.set(key, request);
      const activeTimer = saveTimers.current.get(key);
      if (activeTimer) {
        clearTimeout(activeTimer);
      }
      const flush = () => {
        saveTimers.current.delete(key);
        const latest = latestSaveRequests.current.get(key);
        latestSaveRequests.current.delete(key);
        if (latest) {
          enqueueAnnotation(latest);
        }
      };
      if (immediate) {
        flush();
      } else {
        saveTimers.current.set(key, setTimeout(flush, 400));
      }
    },
    [enqueueAnnotation],
  );

  const flushPendingAnnotations = useCallback(async () => {
    for (const timer of saveTimers.current.values()) {
      clearTimeout(timer);
    }
    saveTimers.current.clear();
    const requests = [...latestSaveRequests.current.values()];
    latestSaveRequests.current.clear();
    requests.forEach(enqueueAnnotation);
    await Promise.all([...saveQueues.current.values()]);
  }, [enqueueAnnotation]);

  const persistNode = useCallback(
    (node: Node<NotationNodeData>, immediate = false) => {
      if (!payload?.graph_id || node.id.startsWith('__')) {
        return;
      }
      scheduleAnnotation(
        {
          graphId: payload.graph_id,
          notation,
          elementId: node.id,
          elementKind: 'node',
          payload: nodeAnnotationPayload(node),
        },
        immediate,
      );
    },
    [notation, payload?.graph_id, scheduleAnnotation],
  );

  const persistEdge = useCallback(
    (edge: Edge<EditableEdgeData>, immediate = false) => {
      if (!payload?.graph_id) {
        return;
      }
      scheduleAnnotation(
        {
          graphId: payload.graph_id,
          notation,
          elementId: edge.id,
          elementKind: 'edge',
          payload: edgeAnnotationPayload(edge),
        },
        immediate,
      );
    },
    [notation, payload?.graph_id, scheduleAnnotation],
  );

  function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!loginForm.username.trim() || !loginForm.password) {
      setError('Введите логин и пароль Graph API.');
      return;
    }
    setAuthUser(loginForm.username.trim());
    setAuthToken(encodeBasicAuth(loginForm.username.trim(), loginForm.password));
    setError('');
  }

  async function logout() {
    await flushPendingAnnotations();
    setAuthToken('');
    setAuthUser('');
    setPayload(null);
    setRuns([]);
    setNodes([]);
    setEdges([]);
    setGroups([]);
    setTemplates([]);
    setViews([]);
    setOccurrences([]);
    setSelectedGroupIds([]);
    setSelected(null);
    setLoginForm({ username: '', password: '' });
    setSaveStatus('');
  }

  async function changeRun(runId: string) {
    await flushPendingAnnotations();
    resetVisualizationState();
    setSelectedRunId(runId);
  }

  async function changeNotation(nextNotation: Notation) {
    await flushPendingAnnotations();
    setNotation(nextNotation);
  }

  function resetVisualizationState() {
    setHiddenNodeTypes([]);
    setHiddenEdgeTypes([]);
    setHiddenLevels([]);
    setCollapsedBranches([]);
    setAttributeFilters({ ...EMPTY_ATTRIBUTE_FILTERS });
    setMetricMode('planned');
    pendingViewport.current = null;
  }

  function toggleBranch(nodeId: string) {
    setCollapsedBranches((current) => toggleValue(current, nodeId));
  }

  function toggleLevel(level: number) {
    setHiddenLevels((current) => (
      current.includes(level) ? current.filter((item) => item !== level) : [...current, level]
    ));
  }

  function updateAttributeFilter(field: keyof AttributeFilters, value: string) {
    setAttributeFilters((current) => ({ ...current, [field]: value }));
  }

  async function saveCurrentView(name: string) {
    if (!payload?.graph_id.startsWith('run:') && !payload?.graph_id.startsWith('graph:')) {
      setError('Текущую карту нельзя сохранить как представление.');
      return;
    }
    setSaveStatus('Сохранение представления...');
    try {
      const saved = await saveGraphView(apiBaseUrl, authToken, {
        graph_id: payload.graph_id,
        view_id: uniqueId('view'),
        name,
        revision: 0,
        state: {
          notation,
          view_mode: viewMode,
          metric_mode: metricMode,
          inverted_background: invertedBackground,
          hidden_node_types: hiddenNodeTypes,
          hidden_edge_types: hiddenEdgeTypes,
          hidden_levels: hiddenLevels,
          attribute_filters: attributeFilters,
          collapsed_branches: collapsedBranches,
          viewport: flowInstance?.getViewport() || {},
        },
      });
      setViews((current) => [saved, ...current.filter((view) => view.view_id !== saved.view_id)]);
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
    }
  }

  async function applySavedView(view: GraphViewRecord) {
    await flushPendingAnnotations();
    const state = view.state;
    setNotation(isNotation(state.notation) ? state.notation : 'flow');
    setViewMode(state.view_mode);
    setMetricMode(state.metric_mode);
    setInvertedBackground(state.inverted_background);
    setHiddenNodeTypes([...state.hidden_node_types]);
    setHiddenEdgeTypes([...state.hidden_edge_types]);
    setHiddenLevels([...state.hidden_levels]);
    setAttributeFilters({ ...state.attribute_filters });
    setCollapsedBranches([...state.collapsed_branches]);
    const viewport = state.viewport as Partial<{ x: number; y: number; zoom: number }>;
    pendingViewport.current = (
      typeof viewport.x === 'number'
      && typeof viewport.y === 'number'
      && typeof viewport.zoom === 'number'
    ) ? { x: viewport.x, y: viewport.y, zoom: viewport.zoom } : null;
    setSelected(null);
    setError('');
    setSaveStatus(`Открыто: ${view.name}`);
  }

  async function removeSavedView(viewId: string) {
    if (!payload?.graph_id) {
      return;
    }
    setSaveStatus('Удаление представления...');
    try {
      await deleteGraphView(apiBaseUrl, authToken, payload.graph_id, viewId);
      setViews((current) => current.filter((view) => view.view_id !== viewId));
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
      setViewRefresh((value) => value + 1);
    }
  }

  function exportGraph(): GraphExport {
    const exportNodes = visibleNodes
      .filter((node) => node.id !== '__system_boundary')
      .filter((node) => !groupIdFromNode(node.id) || Boolean(node.data.raw.collapsed));
    const exportNodeIds = new Set(exportNodes.map((node) => node.id));
    return {
      title: payload?.title || 'GraphFlow',
      nodes: exportNodes.map((node) => {
        const style = effectiveNodeStyle(node.data);
        return {
          id: node.id,
          label: node.data.label,
          nodeType: node.data.nodeType,
          shape: node.data.shape,
          position: node.position,
          width: node.measured?.width,
          height: node.measured?.height,
          fill: String(style.background || '#ffffff'),
          stroke: String(style.borderColor || '#334155'),
          metric: node.data.metricValue
            ? `${metricMode === 'planned' ? 'План' : 'Факт'}: ${node.data.metricValue}`
            : '',
          sharedMapCount: node.data.sharedMapCount,
        };
      }),
      edges: visibleEdges
        .filter((edge) => exportNodeIds.has(edge.source) && exportNodeIds.has(edge.target))
        .map((edge) => {
          const style = edgeTypeStyle(edgeData(edge).edgeType);
          return {
            source: edge.source,
            target: edge.target,
            label: edgeData(edge).label,
            edgeType: edgeData(edge).edgeType,
            stroke: String(style.stroke || '#64748b'),
            dashed: Boolean(style.strokeDasharray),
          };
        }),
    };
  }

  function updateNode(id: string, patch: Partial<NotationNodeData>) {
    const current = nodes.find((node) => node.id === id);
    if (!current) {
      return;
    }
    const next = { ...current, data: { ...current.data, ...patch } };
    setNodes((currentNodes) => currentNodes.map((node) => (node.id === id ? next : node)));
    persistNode(next);
  }

  function updateNodeProperty(id: string, propertyId: string, field: 'key' | 'value', value: string) {
    const current = nodes.find((node) => node.id === id);
    if (!current) {
      return;
    }
    const properties = current.data.properties.map((property) =>
      property.id === propertyId ? { ...property, [field]: value } : property,
    );
    const next = { ...current, data: { ...current.data, properties } };
    setNodes((currentNodes) => currentNodes.map((node) => (node.id === id ? next : node)));
    persistNode(next);
  }

  function addNodeProperty(id: string) {
    const current = nodes.find((node) => node.id === id);
    if (!current) {
      return;
    }
    const next = {
      ...current,
      data: {
        ...current.data,
        properties: [...current.data.properties, newProperty()],
      },
    };
    setNodes((currentNodes) => currentNodes.map((node) => (node.id === id ? next : node)));
    persistNode(next);
  }

  function updateNodePosition(id: string, position: { x: number; y: number }) {
    const current = nodes.find((node) => node.id === id);
    if (!current) {
      return;
    }
    const next = { ...current, position };
    const nextNodes = nodes.map((node) => (node.id === id ? next : node));
    setNodes(nextNodes);
    setEdges((currentEdges) => routeFlowEdges(currentEdges, nextNodes));
    persistNode(next);
  }

  function completeNodeDrag(node: Node<NotationNodeData>) {
    const nextNodes = nodes.map((current) => (current.id === node.id ? node : current));
    setEdges((currentEdges) => routeFlowEdges(currentEdges, nextNodes));
    persistNode(node, true);
  }

  function updateNodePosition3D(id: string, position3d: Position3D, immediate = false) {
    const current = nodes.find((node) => node.id === id);
    if (!current) {
      return;
    }
    const next = { ...current, data: { ...current.data, position3d } };
    setNodes((currentNodes) => currentNodes.map((node) => (node.id === id ? next : node)));
    persistNode(next, immediate);
  }

  function resetNodeField(
    id: string,
    field:
      | 'label'
      | 'shape'
      | 'imageUrl'
      | 'createdAt'
      | 'endedAt'
      | 'properties'
      | 'position'
      | 'position3d',
  ) {
    const current = nodes.find((node) => node.id === id);
    if (!current) {
      return;
    }
    const base = current.data.base;
    const dataPatch =
      field === 'properties'
        ? { properties: base.properties }
        : field === 'position'
          ? {}
          : { [field]: base[field] };
    const next = {
      ...current,
      position: field === 'position' ? base.position : current.position,
      data: { ...current.data, ...dataPatch },
    };
    setNodes((currentNodes) => currentNodes.map((node) => (node.id === id ? next : node)));
    persistNode(next);
  }

  function updateEdge(id: string, patch: Partial<EditableEdgeData>) {
    const current = edges.find((edge) => edge.id === id);
    if (!current) {
      return;
    }
    const data = edgeData(current);
    const edgeType = patch.edgeType ?? data.edgeType;
    const label = patch.label ?? data.label;
    const next = withEdgePresentation(current, { ...data, ...patch, edgeType, label });
    setEdges((currentEdges) => currentEdges.map((edge) => (edge.id === id ? next : edge)));
    persistEdge(next);
  }

  function updateEdgeProperty(id: string, propertyId: string, field: 'key' | 'value', value: string) {
    const current = edges.find((edge) => edge.id === id);
    if (!current) {
      return;
    }
    const data = edgeData(current);
    const properties = data.properties.map((property) =>
      property.id === propertyId ? { ...property, [field]: value } : property,
    );
    const next = { ...current, data: { ...data, properties } };
    setEdges((currentEdges) => currentEdges.map((edge) => (edge.id === id ? next : edge)));
    persistEdge(next);
  }

  function addEdgeProperty(id: string) {
    const current = edges.find((edge) => edge.id === id);
    if (!current) {
      return;
    }
    const data = edgeData(current);
    const next = {
      ...current,
      data: { ...data, properties: [...data.properties, newProperty()] },
    };
    setEdges((currentEdges) => currentEdges.map((edge) => (edge.id === id ? next : edge)));
    persistEdge(next);
  }

  function resetEdgeField(id: string, field: 'label' | 'edgeType' | 'properties') {
    const current = edges.find((edge) => edge.id === id);
    if (!current) {
      return;
    }
    const data = edgeData(current);
    const base = data.base;
    const edgeType = field === 'edgeType' ? base.edgeType : data.edgeType;
    const label = field === 'label' ? base.label : data.label;
    const properties = field === 'properties' ? base.properties : data.properties;
    const next = withEdgePresentation(current, { ...data, edgeType, label, properties });
    setEdges((currentEdges) => currentEdges.map((edge) => (edge.id === id ? next : edge)));
    persistEdge(next);
  }

  function toggleNodeType(type: string) {
    setHiddenNodeTypes((current) => toggleValue(current, type));
  }

  function toggleEdgeType(type: string) {
    setHiddenEdgeTypes((current) => toggleValue(current, type));
  }

  async function persistGroup(
    group: Omit<GraphGroupRecord, 'created_at' | 'updated_at'>,
  ): Promise<GraphGroupRecord | null> {
    setSaveStatus('Сохранение группы...');
    try {
      const saved = await saveGraphGroup(apiBaseUrl, authToken, group);
      setGroups((current) => [
        ...current.filter((item) => item.group_id !== saved.group_id),
        saved,
      ]);
      setError('');
      setSaveStatus('Сохранено');
      return saved;
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
      setGroupRefresh((value) => value + 1);
      return null;
    }
  }

  async function createGroup(title: string) {
    if (!payload?.graph_id) {
      return;
    }
    const groupsById = new Map(groups.map((group) => [group.group_id, group]));
    const nodesInSelectedGroups = new Set(
      selectedGroupIds.flatMap((groupId) => [...recursiveGroupNodeIds(groupId, groupsById)]),
    );
    const nodeIds = selectedNodeIds.filter((nodeId) => !nodesInSelectedGroups.has(nodeId));
    const directOwners = new Map(
      groups.flatMap((group) => group.node_ids.map((nodeId) => [nodeId, group.group_id] as const)),
    );
    const occupiedNode = nodeIds.find((nodeId) => directOwners.has(nodeId));
    if (occupiedNode) {
      setError(`Узел уже входит в группу ${directOwners.get(occupiedNode)}.`);
      return;
    }
    if (nodeIds.length + selectedGroupIds.length < 2) {
      setError('Для группирования выберите не менее двух узлов или групп.');
      return;
    }
    const saved = await persistGroup({
      graph_id: payload.graph_id,
      notation,
      group_id: uniqueId('group'),
      title: title.trim() || 'Новая группа',
      node_ids: nodeIds,
      child_group_ids: selectedGroupIds,
      collapsed: false,
      revision: 0,
    });
    if (saved) {
      setSelectedGroupIds([]);
    }
  }

  async function toggleGroup(groupId: string) {
    const group = groups.find((item) => item.group_id === groupId);
    if (!group) {
      return;
    }
    await persistGroup({
      graph_id: group.graph_id,
      notation: group.notation,
      group_id: group.group_id,
      title: group.title,
      node_ids: group.node_ids,
      child_group_ids: group.child_group_ids,
      collapsed: !group.collapsed,
      revision: group.revision,
    });
  }

  async function setAllGroupsCollapsed(collapsed: boolean) {
    const changed = groups.filter((group) => group.collapsed !== collapsed);
    if (changed.length === 0) {
      return;
    }
    setSaveStatus('Сохранение групп...');
    try {
      const saved = await Promise.all(
        changed.map((group) => saveGraphGroup(apiBaseUrl, authToken, {
          graph_id: group.graph_id,
          notation: group.notation,
          group_id: group.group_id,
          title: group.title,
          node_ids: group.node_ids,
          child_group_ids: group.child_group_ids,
          collapsed,
          revision: group.revision,
        })),
      );
      const savedById = new Map(saved.map((group) => [group.group_id, group]));
      setGroups((current) => current.map((group) => savedById.get(group.group_id) || group));
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
      setGroupRefresh((value) => value + 1);
    }
  }

  async function removeGroup(groupId: string) {
    if (!payload?.graph_id) {
      return;
    }
    setSaveStatus('Удаление группы...');
    try {
      await deleteGraphGroup(apiBaseUrl, authToken, payload.graph_id, notation, groupId);
      setGroups((current) => current.filter((group) => group.group_id !== groupId));
      setSelectedGroupIds((current) => current.filter((id) => id !== groupId));
      setGroupRefresh((value) => value + 1);
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
    }
  }

  async function collapseSelectedDescendants() {
    if (!payload?.graph_id || !selectedNode) {
      setError('Выберите корневой узел дочернего графа.');
      return;
    }
    const descendants = descendantNodeIds(
      selectedNode.id,
      edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: edgeData(edge).edgeType,
        label: edgeData(edge).label,
      })),
      CHILD_EDGE_TYPES,
    );
    if (descendants.length === 0) {
      setError('У выбранного узла нет дочерних связей contains, include или properties.');
      return;
    }
    await persistGroup({
      graph_id: payload.graph_id,
      notation,
      group_id: uniqueId('children'),
      title: `Дочерние: ${selectedNode.data.label}`,
      node_ids: descendants,
      child_group_ids: [],
      collapsed: true,
      revision: 0,
    });
  }

  async function saveTemplate(name: string, scope: 'selection' | 'graph') {
    const realNodes = nodes.filter((node) => !node.id.startsWith('__'));
    const scopeNodeIds = scope === 'graph'
      ? new Set(realNodes.map((node) => node.id))
      : new Set(selectedNodeIds);
    if (scopeNodeIds.size === 0) {
      setError('Для шаблона выберите хотя бы один узел.');
      return;
    }
    const definition = templateDefinition(realNodes, edges, groups, scopeNodeIds);
    setSaveStatus('Сохранение шаблона...');
    try {
      await saveGraphTemplate(apiBaseUrl, authToken, {
        template_id: uniqueId('template'),
        name: name.trim() || 'Новый шаблон',
        description: payload?.title || '',
        notation,
        revision: 0,
        definition,
      });
      setTemplateRefresh((value) => value + 1);
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
    }
  }

  async function applyTemplate(templateId: string) {
    if (!payload?.graph_id.startsWith('graph:')) {
      setError('Шаблон можно добавить только в редактируемый пользовательский граф.');
      return;
    }
    const controller = new AbortController();
    setSaveStatus('Добавление шаблона...');
    try {
      const template = await loadGraphTemplate(
        apiBaseUrl,
        authToken,
        templateId,
        controller.signal,
      );
      const instanceId = uniqueId('instance');
      const nodeIds = new Map(
        template.definition.nodes.map((node, index) => [
          node.id,
          `${instanceId}-node-${index + 1}`,
        ]),
      );
      const groupIds = new Map(
        template.definition.groups.map((group, index) => [
          group.group_id,
          `${instanceId}-group-${index + 1}`,
        ]),
      );
      const maxX = Math.max(0, ...nodes
        .filter((node) => !node.id.startsWith('__'))
        .map((node) => node.position.x + (node.measured?.width || 220)));
      const insertedNodes = template.definition.nodes.map((node) => ({
        ...node,
        id: nodeIds.get(node.id)!,
        x: node.x + maxX + 180,
        y: node.y,
        position3d: { ...node.position3d, x: node.position3d.x + 80 },
      }));
      const insertedEdges = template.definition.edges.map((edge, index) => ({
        ...edge,
        id: `${instanceId}-edge-${index + 1}`,
        source: nodeIds.get(edge.source)!,
        target: nodeIds.get(edge.target)!,
      }));
      const graphId = payload.graph_id.replace(/^graph:/, '');
      await saveCustomGraphDefinition(apiBaseUrl, authToken, {
        graph_id: graphId,
        title: payload.title || 'Пользовательский граф',
        source_type: 'manual',
        nodes: [
          ...nodes.filter((node) => !node.id.startsWith('__')).map(customNodePayload),
          ...insertedNodes,
        ],
        edges: [...edges.map(customEdgePayload), ...insertedEdges],
      });
      for (const group of childFirstGroups(template.definition.groups)) {
        await saveGraphGroup(apiBaseUrl, authToken, {
          graph_id: payload.graph_id,
          notation,
          group_id: groupIds.get(group.group_id)!,
          title: group.title,
          node_ids: group.node_ids.map((id) => nodeIds.get(id)!),
          child_group_ids: group.child_group_ids.map((id) => groupIds.get(id)!),
          collapsed: group.collapsed,
          revision: 0,
        });
      }
      setGraphRefresh((value) => value + 1);
      setGroupRefresh((value) => value + 1);
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
    }
  }

  async function removeTemplate(templateId: string) {
    setSaveStatus('Удаление шаблона...');
    try {
      await deleteGraphTemplate(apiBaseUrl, authToken, templateId);
      setTemplates((current) => current.filter((item) => item.template_id !== templateId));
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
    }
  }

  async function saveGraphDefinition(
    graphId: string,
    title: string,
    graphNodes: Node<NotationNodeData>[],
    graphEdges: Edge<EditableEdgeData>[],
  ) {
    setSaveStatus('Сохранение графа...');
    try {
      await saveCustomGraphDefinition(apiBaseUrl, authToken, {
        graph_id: graphId,
        title,
        source_type: 'manual',
        nodes: graphNodes
          .filter((node) => !node.id.startsWith('__'))
          .map(customNodePayload),
        edges: graphEdges.map(customEdgePayload),
      });
      setSelectedRunId(`graph:${graphId}`);
      setGraphRefresh((value) => value + 1);
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
    }
  }

  function createEditableCopy() {
    const graphId = `manual-${crypto.randomUUID?.() || Date.now()}`;
    void saveGraphDefinition(graphId, payload?.title || 'Пользовательский граф', nodes, edges);
  }

  function addCustomNode(label: string, nodeType: string) {
    if (!payload?.graph_id.startsWith('graph:')) {
      return;
    }
    const nodeId = `node-${crypto.randomUUID?.() || Date.now()}`;
    const base: BaseNodeState = {
      label,
      shape: 'rounded_rectangle',
      imageUrl: '',
      createdAt: new Date().toISOString(),
      endedAt: '',
      position: { x: 0, y: 0 },
      position3d: { x: 0, y: 0, z: 0 },
      properties: [],
    };
    const node: Node<NotationNodeData> = {
      id: nodeId,
      type: 'notationNode',
      position: base.position,
      data: {
        label,
        shape: base.shape,
        nodeType,
        imageUrl: '',
        createdAt: base.createdAt,
        endedAt: base.endedAt,
        position3d: base.position3d,
        properties: [],
        annotationRevision: 0,
        base,
        style: {},
        raw: { class: 'GraphNode' },
      },
    };
    void saveGraphDefinition(
      payload.graph_id.replace(/^graph:/, ''),
      payload.title || 'Пользовательский граф',
      [...nodes, node],
      edges,
    );
  }

  function addCustomEdge(source: string, target: string, edgeType: string) {
    if (!payload?.graph_id.startsWith('graph:') || source === target) {
      return;
    }
    const edgeId = `edge-${crypto.randomUUID?.() || Date.now()}`;
    const base: BaseEdgeState = { label: edgeType, edgeType, properties: [] };
    const edge: Edge<EditableEdgeData> = {
      id: edgeId,
      source,
      target,
      label: edgeType,
      type: 'readable',
      data: {
        label: edgeType,
        edgeType,
        showLabel: true,
        properties: [],
        annotationRevision: 0,
        base,
        raw: { class: 'GraphConnection' },
      },
      style: edgeTypeStyle(edgeType),
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    };
    const nextEdges = routeFlowEdges([...edges, edge], nodes);
    void saveGraphDefinition(
      payload.graph_id.replace(/^graph:/, ''),
      payload.title || 'Пользовательский граф',
      nodes,
      nextEdges,
    );
  }

  async function applyLayout(mode: LayoutMode) {
    if (mode === 'follow' && !visibleEdges.some((edge) => edgeData(edge).edgeType === 'follow')) {
      setError('Для раскладки Follow в текущем фильтре нет связей типа follow.');
      return;
    }
    if (
      mode === 'timeline'
      && !visibleNodes.some((node) => parseCreatedAt(node.data.createdAt) !== Number.MAX_SAFE_INTEGER)
    ) {
      setError('Для Timeline заполните Created At хотя бы у одного узла.');
      return;
    }
    await flushPendingAnnotations();

    const arrangedVisible = arrangeNodes(visibleNodes, visibleEdges, mode);
    const arrangedById = new Map(arrangedVisible.map((node) => [node.id, node]));
    const arranged = nodes.map((node) => arrangedById.get(node.id) || node);
    setNodes(arranged);
    setEdges((currentEdges) =>
      routeFlowEdges(currentEdges, arranged, mode === 'structure' ? 'vertical' : 'horizontal'),
    );
    window.requestAnimationFrame(() =>
      flowInstance?.fitView({ padding: 0.12, minZoom: 0.58, duration: 300 }),
    );
    if (!payload?.graph_id) {
      return;
    }
    const items = arrangedVisible
      .filter((node) => !node.id.startsWith('__'))
      .map((node) => {
        const key = annotationKey('node', node.id, notation);
        return {
          graph_id: payload.graph_id,
          notation,
          element_id: node.id,
          element_kind: 'node' as const,
          revision: annotationRevisions.current.get(key) || 0,
          payload: { position: node.position },
        };
      });
    if (items.length === 0) {
      return;
    }
    setSaveStatus('Сохранение раскладки...');
    try {
      const response = await saveAnnotationsBatch(apiBaseUrl, authToken, items);
      response.items.forEach((item) => {
        annotationRevisions.current.set(
          annotationKey(item.element_kind, item.element_id, notation),
          item.revision,
        );
      });
      setError('');
      setSaveStatus('Сохранено');
    } catch (requestError) {
      handleRequestError(requestError as Error, setAuthToken, setError, setSaveStatus);
    }
  }

  if (!authToken) {
    return (
      <LoginView
        error={error}
        loginForm={loginForm}
        onChange={setLoginForm}
        onSubmit={submitLogin}
      />
    );
  }

  return (
    <ReactFlowProvider>
      <div className={`graph-page${invertedBackground ? ' theme-dark' : ''}`}>
        <header className="graph-toolbar">
          <div>
            <div className="toolbar-title-row">
              <h1>{payload?.title || 'Последний запуск пайплайна'}</h1>
            </div>
            <p>
              {notationLabel(notation)} / узлы{' '}
              {visibleNodes.filter((node) => !node.id.startsWith('__')).length} из{' '}
              {nodes.filter((node) => !node.id.startsWith('__')).length} / связи{' '}
              {visibleEdges.length} из {edges.length}
            </p>
          </div>
          <div className="toolbar-controls">
            {saveStatus ? <span className="save-status">{saveStatus}</span> : null}
            <span className="auth-user">{authUser}</span>
            <div className="view-mode" role="group" aria-label="Режим отображения">
              <button
                type="button"
                className={viewMode === '2d' ? 'is-active' : ''}
                onClick={() => setViewMode('2d')}
              >
                2D
              </button>
              <button
                type="button"
                className={viewMode === '3d' ? 'is-active' : ''}
                onClick={() => setViewMode('3d')}
              >
                3D
              </button>
            </div>
            <div className="view-mode" role="group" aria-label="Плановые и фактические значения">
              <button
                type="button"
                className={metricMode === 'planned' ? 'is-active' : ''}
                onClick={() => setMetricMode('planned')}
              >
                План
              </button>
              <button
                type="button"
                className={metricMode === 'actual' ? 'is-active' : ''}
                onClick={() => setMetricMode('actual')}
              >
                Факт
              </button>
            </div>
            <label className="background-toggle">
              <input
                type="checkbox"
                checked={invertedBackground}
                onChange={(event) => setInvertedBackground(event.target.checked)}
              />
              Темная тема
            </label>
            <label className="toolbar-field toolbar-map-field">
              <span>Карта</span>
              <select
                value={selectedRunId}
                disabled={isLoading}
                onChange={(event) => void changeRun(event.target.value)}
              >
                {runs.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {runOptionLabel(run)}
                  </option>
                ))}
              </select>
            </label>
            <label className="toolbar-field">
              <span>Нотация</span>
              <select
                value={notation}
                disabled={isLoading}
                onChange={(event) => void changeNotation(event.target.value as Notation)}
              >
                {NOTATIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" onClick={() => void logout()}>
              Выйти
            </button>
          </div>
        </header>

        <div className={`graph-error-slot${error ? ' has-error' : ''}`}>
          {error || '\u00a0'}
        </div>

        <main className="graph-layout">
          <GraphFilters
            nodeTypes={nodeTypeOptions}
            edgeTypes={edgeTypeOptions}
            hiddenNodeTypes={hiddenNodeTypes}
            hiddenEdgeTypes={hiddenEdgeTypes}
            onToggleNodeType={toggleNodeType}
            onToggleEdgeType={toggleEdgeType}
            onReset={resetVisualizationState}
            onApplyLayout={applyLayout}
            showLayouts={viewMode === '2d'}
            editableGraph={Boolean(payload?.graph_id.startsWith('graph:'))}
            nodeOptions={nodes
              .filter((node) => !node.id.startsWith('__'))
              .map((node) => ({ id: node.id, label: node.data.label }))}
            groups={groups}
            templates={templates}
            selectedNodeCount={selectedNodeIds.length}
            selectedGroupIds={selectedGroupIds}
            onCreateCopy={createEditableCopy}
            onAddNode={addCustomNode}
            onAddEdge={addCustomEdge}
            onToggleGroupSelection={(groupId) =>
              setSelectedGroupIds((current) => toggleValue(current, groupId))
            }
            onCreateGroup={createGroup}
            onToggleGroup={toggleGroup}
            onDeleteGroup={removeGroup}
            onSetAllGroupsCollapsed={setAllGroupsCollapsed}
            onCollapseDescendants={collapseSelectedDescendants}
            canCollapseDescendants={Boolean(selectedNode)}
            onSaveTemplate={saveTemplate}
            onApplyTemplate={applyTemplate}
            onDeleteTemplate={removeTemplate}
            attributeOptions={metadataOptions}
            attributeFilters={attributeFilters}
            onAttributeFilterChange={updateAttributeFilter}
            levels={levelOptions}
            hiddenLevels={hiddenLevels}
            onToggleLevel={toggleLevel}
            views={views}
            onSaveView={saveCurrentView}
            onApplyView={applySavedView}
            onDeleteView={removeSavedView}
            onExportSvg={() => downloadGraphSvg(exportGraph())}
            onExportPresentation={() => downloadGraphPresentation(exportGraph())}
          />
          <section
            className={`graph-canvas${invertedBackground ? ' is-inverted' : ''}`}
            aria-label="Интерактивный граф"
          >
            {isLoading ? <div className="graph-loading">Загрузка графа...</div> : null}
            {viewMode === '2d' ? (
              <ReactFlow
                nodes={visibleNodes}
                edges={visibleEdges}
                nodeTypes={nodeTypes}
                edgeTypes={flowEdgeTypes}
                onInit={setFlowInstance}
                fitView
                fitViewOptions={{ padding: 0.12, minZoom: 0.58 }}
                minZoom={0.25}
                maxZoom={2}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeDragStop={(_, node) => completeNodeDrag(node as Node<NotationNodeData>)}
                onNodeClick={(_, node) => {
                  const groupId = groupIdFromNode(node.id);
                  if (groupId) {
                    void toggleGroup(groupId);
                  } else {
                    setSelected({ kind: 'node', id: node.id });
                  }
                }}
                onEdgeClick={(_, edge) => setSelected({
                  kind: 'edge',
                  id: edgeData(edge as Edge<EditableEdgeData>).sourceEdgeIds?.[0] || edge.id,
                })}
                onPaneClick={() => setSelected(null)}
                selectionOnDrag
                multiSelectionKeyCode="Control"
                colorMode={invertedBackground ? 'dark' : 'light'}
                proOptions={{ hideAttribution: true }}
              >
                <Background
                  color={invertedBackground ? '#303946' : '#cbd5e1'}
                  gap={24}
                  size={1}
                />
                <Controls />
                <MiniMap pannable zoomable />
              </ReactFlow>
            ) : (
              <Suspense fallback={<div className="graph-loading">Инициализация 3D...</div>}>
                <Graph3DView
                  nodes={graph3dNodes}
                  links={graph3dLinks}
                  selectedNodeId={selected?.kind === 'node' ? selected.id : undefined}
                  selectedEdgeId={selected?.kind === 'edge' ? selected.id : undefined}
                  invertedBackground={invertedBackground}
                  onSelectNode={(id) => {
                    const groupId = groupIdFromNode(id);
                    if (groupId) {
                      void toggleGroup(groupId);
                    } else {
                      setSelected({ kind: 'node', id });
                    }
                  }}
                  onSelectEdge={(id) => setSelected({ kind: 'edge', id })}
                  onClearSelection={() => setSelected(null)}
                  onNodePositionChange={(id, position) =>
                    updateNodePosition3D(id, position, true)
                  }
                />
              </Suspense>
            )}
            <GraphLegend
              nodeEntries={nodeLegendEntries}
              edgeEntries={edgeLegendEntries}
              statusEntries={statusLegendEntries}
              hasSharedNodes={visibleNodes.some((node) => (node.data.sharedMapCount || 1) > 1)}
            />
          </section>

          <Inspector
            selectedNode={isLoading ? undefined : selectedNode}
            selectedEdge={isLoading ? undefined : selectedEdge}
            onUpdateNode={updateNode}
            onUpdateNodePosition={updateNodePosition}
            onUpdateNodePosition3D={updateNodePosition3D}
            onUpdateNodeProperty={updateNodeProperty}
            onAddNodeProperty={addNodeProperty}
            onResetNodeField={resetNodeField}
            onUpdateEdge={updateEdge}
            onUpdateEdgeProperty={updateEdgeProperty}
            onAddEdgeProperty={addEdgeProperty}
            onResetEdgeField={resetEdgeField}
            onError={setError}
            metricMode={metricMode}
            sharedMapCount={selectedNode
              ? occurrencesByKey.get(canonicalNodeLabel(selectedNode.data.label))?.map_count || 1
              : 1}
          />
        </main>
      </div>
    </ReactFlowProvider>
  );
}

function LoginView({
  error,
  loginForm,
  onChange,
  onSubmit,
}: {
  error: string;
  loginForm: { username: string; password: string };
  onChange: (value: { username: string; password: string }) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="login-page">
      <div className="login-shell">
        <div className="login-brand" aria-label="GraphFlow">
          <span className="login-brand-mark" aria-hidden="true">GF</span>
          <span>GraphFlow</span>
        </div>
        <form className="login-form" onSubmit={onSubmit}>
          <div className="login-heading">
            <h1>Вход в систему</h1>
          </div>
          <label>
            Логин
            <input
              value={loginForm.username}
              autoComplete="username"
              autoFocus
              onChange={(event) => onChange({ ...loginForm, username: event.target.value })}
            />
          </label>
          <label>
            Пароль
            <input
              value={loginForm.password}
              type="password"
              autoComplete="current-password"
              onChange={(event) => onChange({ ...loginForm, password: event.target.value })}
            />
          </label>
          {error ? <div className="login-error">{error}</div> : null}
          <button type="submit">Войти</button>
        </form>
      </div>
    </div>
  );
}

function GraphFilters({
  nodeTypes,
  edgeTypes,
  hiddenNodeTypes,
  hiddenEdgeTypes,
  onToggleNodeType,
  onToggleEdgeType,
  onReset,
  onApplyLayout,
  showLayouts,
  editableGraph,
  nodeOptions,
  groups,
  templates,
  selectedNodeCount,
  selectedGroupIds,
  onCreateCopy,
  onAddNode,
  onAddEdge,
  onToggleGroupSelection,
  onCreateGroup,
  onToggleGroup,
  onDeleteGroup,
  onSetAllGroupsCollapsed,
  onCollapseDescendants,
  canCollapseDescendants,
  onSaveTemplate,
  onApplyTemplate,
  onDeleteTemplate,
  attributeOptions,
  attributeFilters,
  onAttributeFilterChange,
  levels,
  hiddenLevels,
  onToggleLevel,
  views,
  onSaveView,
  onApplyView,
  onDeleteView,
  onExportSvg,
  onExportPresentation,
}: {
  nodeTypes: string[];
  edgeTypes: string[];
  hiddenNodeTypes: string[];
  hiddenEdgeTypes: string[];
  onToggleNodeType: (type: string) => void;
  onToggleEdgeType: (type: string) => void;
  onReset: () => void;
  onApplyLayout: (mode: LayoutMode) => void;
  showLayouts: boolean;
  editableGraph: boolean;
  nodeOptions: Array<{ id: string; label: string }>;
  groups: GraphGroupRecord[];
  templates: GraphTemplateRecord[];
  selectedNodeCount: number;
  selectedGroupIds: string[];
  onCreateCopy: () => void;
  onAddNode: (label: string, nodeType: string) => void;
  onAddEdge: (source: string, target: string, edgeType: string) => void;
  onToggleGroupSelection: (groupId: string) => void;
  onCreateGroup: (title: string) => void;
  onToggleGroup: (groupId: string) => void;
  onDeleteGroup: (groupId: string) => void;
  onSetAllGroupsCollapsed: (collapsed: boolean) => void;
  onCollapseDescendants: () => void;
  canCollapseDescendants: boolean;
  onSaveTemplate: (name: string, scope: 'selection' | 'graph') => void;
  onApplyTemplate: (templateId: string) => void;
  onDeleteTemplate: (templateId: string) => void;
  attributeOptions: AttributeOptions;
  attributeFilters: AttributeFilters;
  onAttributeFilterChange: (field: keyof AttributeFilters, value: string) => void;
  levels: Array<{ level: number; count: number }>;
  hiddenLevels: number[];
  onToggleLevel: (level: number) => void;
  views: GraphViewRecord[];
  onSaveView: (name: string) => void;
  onApplyView: (view: GraphViewRecord) => void;
  onDeleteView: (viewId: string) => void;
  onExportSvg: () => void;
  onExportPresentation: () => void;
}) {
  const [nodeLabel, setNodeLabel] = useState('Новый узел');
  const [nodeType, setNodeType] = useState('process');
  const [edgeSource, setEdgeSource] = useState('');
  const [edgeTarget, setEdgeTarget] = useState('');
  const [newEdgeType, setNewEdgeType] = useState('follow');
  const [groupTitle, setGroupTitle] = useState('Новая группа');
  const [templateName, setTemplateName] = useState('Новый шаблон');
  useEffect(() => {
    if (!nodeOptions.some((node) => node.id === edgeSource)) {
      setEdgeSource(nodeOptions[0]?.id || '');
    }
    if (!nodeOptions.some((node) => node.id === edgeTarget)) {
      setEdgeTarget(nodeOptions[1]?.id || nodeOptions[0]?.id || '');
    }
  }, [edgeSource, edgeTarget, nodeOptions]);
  return (
    <aside className="graph-filters">
      <div className="filter-header">
        <h2>Фильтры</h2>
        <button type="button" onClick={onReset}>
          Сбросить
        </button>
      </div>
      <section className="filter-section">
        <h3>Типы узлов</h3>
        {nodeTypes.map((type) => (
          <label className="filter-option" key={type}>
            <input
              type="checkbox"
              checked={!hiddenNodeTypes.includes(type)}
              onChange={() => onToggleNodeType(type)}
            />
            {type}
          </label>
        ))}
      </section>
      <section className="filter-section">
        <h3>Типы ребер</h3>
        {edgeTypes.map((type) => (
          <label className="filter-option" key={type}>
            <input
              type="checkbox"
              checked={!hiddenEdgeTypes.includes(type)}
              onChange={() => onToggleEdgeType(type)}
            />
            <span
              className="edge-type-swatch"
              style={{ background: String(edgeTypeStyle(type).stroke) }}
              aria-hidden="true"
            />
            {type}
          </label>
        ))}
      </section>
      <VisualizationTools
        attributeOptions={attributeOptions}
        filters={attributeFilters}
        onFilterChange={onAttributeFilterChange}
        levels={levels}
        hiddenLevels={hiddenLevels}
        onToggleLevel={onToggleLevel}
        views={views}
        onSaveView={onSaveView}
        onApplyView={onApplyView}
        onDeleteView={onDeleteView}
        onExportSvg={onExportSvg}
        onExportPresentation={onExportPresentation}
      />
      {showLayouts ? (
        <section className="filter-section">
          <h3>Раскладка</h3>
          <div className="layout-actions">
            <button className="layout-primary" type="button" onClick={() => onApplyLayout('overview')}>
              Упорядочить граф
            </button>
            <button type="button" onClick={() => onApplyLayout('follow')}>
              Follow слева направо
            </button>
            <button type="button" onClick={() => onApplyLayout('timeline')}>
              Timeline
            </button>
            <button type="button" onClick={() => onApplyLayout('structure')}>
              Structure дерево
            </button>
          </div>
        </section>
      ) : null}
      <section className="filter-section workspace-section">
        <h3>Группы</h3>
        <input
          value={groupTitle}
          aria-label="Название группы"
          onChange={(event) => setGroupTitle(event.target.value)}
        />
        <button
          type="button"
          disabled={selectedNodeCount + selectedGroupIds.length < 2}
          onClick={() => onCreateGroup(groupTitle)}
        >
          Сгруппировать выбранное ({selectedNodeCount + selectedGroupIds.length})
        </button>
        <button
          type="button"
          disabled={!canCollapseDescendants}
          onClick={onCollapseDescendants}
        >
          Свернуть дочерний граф
        </button>
        {groups.length > 0 ? (
          <>
            <div className="compact-actions">
              <button type="button" onClick={() => onSetAllGroupsCollapsed(true)}>
                Свернуть все
              </button>
              <button type="button" onClick={() => onSetAllGroupsCollapsed(false)}>
                Развернуть все
              </button>
            </div>
            <div className="workspace-list">
              {groups.map((group) => (
                <div className="workspace-list-item" key={group.group_id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={selectedGroupIds.includes(group.group_id)}
                      onChange={() => onToggleGroupSelection(group.group_id)}
                    />
                    <span>
                      <strong>{group.title}</strong>
                      <small>
                        {group.node_ids.length} узл. / {group.child_group_ids.length} гр.
                      </small>
                    </span>
                  </label>
                  <div className="workspace-item-actions">
                    <button type="button" onClick={() => onToggleGroup(group.group_id)}>
                      {group.collapsed ? 'Развернуть' : 'Свернуть'}
                    </button>
                    <button type="button" onClick={() => onDeleteGroup(group.group_id)}>
                      Удалить
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : null}
      </section>
      <section className="filter-section workspace-section">
        <h3>Шаблоны</h3>
        <input
          value={templateName}
          aria-label="Название шаблона"
          onChange={(event) => setTemplateName(event.target.value)}
        />
        <div className="compact-actions">
          <button
            type="button"
            disabled={selectedNodeCount === 0}
            onClick={() => onSaveTemplate(templateName, 'selection')}
          >
            Из выбранного
          </button>
          <button type="button" onClick={() => onSaveTemplate(templateName, 'graph')}>
            Из графа
          </button>
        </div>
        {templates.length > 0 ? (
          <div className="workspace-list">
            {templates.map((template) => (
              <div className="workspace-list-item" key={template.template_id}>
                <div className="template-heading">
                  <strong>{template.name}</strong>
                  <small>{notationLabel(template.notation as Notation)}</small>
                </div>
                <div className="workspace-item-actions">
                  <button
                    type="button"
                    disabled={!editableGraph}
                    onClick={() => onApplyTemplate(template.template_id)}
                  >
                    Добавить
                  </button>
                  <button type="button" onClick={() => onDeleteTemplate(template.template_id)}>
                    Удалить
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </section>
      <section className="filter-section">
        <h3>Редактирование структуры</h3>
        <button type="button" onClick={onCreateCopy}>
          Создать редактируемую копию
        </button>
        {editableGraph ? (
          <div className="structure-editor">
            <input value={nodeLabel} onChange={(event) => setNodeLabel(event.target.value)} />
            <select value={nodeType} onChange={(event) => setNodeType(event.target.value)}>
              <option value="process">process</option>
              <option value="section">section</option>
              <option value="task">task</option>
              <option value="goal">goal</option>
              <option value="milestone">milestone</option>
              <option value="organization">organization</option>
              <option value="result">result</option>
            </select>
            <button type="button" onClick={() => onAddNode(nodeLabel.trim() || 'Новый узел', nodeType)}>
              Добавить узел
            </button>
            <select value={edgeSource} onChange={(event) => setEdgeSource(event.target.value)}>
              {nodeOptions.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}
            </select>
            <select value={edgeTarget} onChange={(event) => setEdgeTarget(event.target.value)}>
              {nodeOptions.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}
            </select>
            <select value={newEdgeType} onChange={(event) => setNewEdgeType(event.target.value)}>
              {EDGE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
            <button
              type="button"
              disabled={!edgeSource || !edgeTarget || edgeSource === edgeTarget}
              onClick={() => onAddEdge(edgeSource, edgeTarget, newEdgeType)}
            >
              Добавить ребро
            </button>
          </div>
        ) : null}
      </section>
    </aside>
  );
}

function Inspector({
  selectedNode,
  selectedEdge,
  onUpdateNode,
  onUpdateNodePosition,
  onUpdateNodePosition3D,
  onUpdateNodeProperty,
  onAddNodeProperty,
  onResetNodeField,
  onUpdateEdge,
  onUpdateEdgeProperty,
  onAddEdgeProperty,
  onResetEdgeField,
  onError,
  metricMode,
  sharedMapCount,
}: {
  selectedNode?: Node<NotationNodeData>;
  selectedEdge?: Edge<EditableEdgeData>;
  onUpdateNode: (id: string, patch: Partial<NotationNodeData>) => void;
  onUpdateNodePosition: (id: string, position: { x: number; y: number }) => void;
  onUpdateNodePosition3D: (id: string, position: Position3D) => void;
  onUpdateNodeProperty: (
    id: string,
    propertyId: string,
    field: 'key' | 'value',
    value: string,
  ) => void;
  onAddNodeProperty: (id: string) => void;
  onResetNodeField: (
    id: string,
    field:
      | 'label'
      | 'shape'
      | 'imageUrl'
      | 'createdAt'
      | 'endedAt'
      | 'properties'
      | 'position'
      | 'position3d',
  ) => void;
  onUpdateEdge: (id: string, patch: Partial<EditableEdgeData>) => void;
  onUpdateEdgeProperty: (
    id: string,
    propertyId: string,
    field: 'key' | 'value',
    value: string,
  ) => void;
  onAddEdgeProperty: (id: string) => void;
  onResetEdgeField: (id: string, field: 'label' | 'edgeType' | 'properties') => void;
  onError: (message: string) => void;
  metricMode: MetricMode;
  sharedMapCount: number;
}) {
  return (
    <aside className="graph-inspector">
      <h2>Свойства</h2>
      {selectedNode ? (
        <NodeEditor
          node={selectedNode}
          onUpdate={onUpdateNode}
          onUpdatePosition={onUpdateNodePosition}
          onUpdatePosition3D={onUpdateNodePosition3D}
          onUpdateProperty={onUpdateNodeProperty}
          onAddProperty={onAddNodeProperty}
          onResetField={onResetNodeField}
          onError={onError}
          metricMode={metricMode}
          sharedMapCount={sharedMapCount}
        />
      ) : null}
      {selectedEdge ? (
        <EdgeEditor
          edge={selectedEdge}
          onUpdate={onUpdateEdge}
          onUpdateProperty={onUpdateEdgeProperty}
          onAddProperty={onAddEdgeProperty}
          onResetField={onResetEdgeField}
        />
      ) : null}
      {!selectedNode && !selectedEdge ? <p>Выберите узел или стрелку на графе.</p> : null}
    </aside>
  );
}

function NodeEditor({
  node,
  onUpdate,
  onUpdatePosition,
  onUpdatePosition3D,
  onUpdateProperty,
  onAddProperty,
  onResetField,
  onError,
  metricMode,
  sharedMapCount,
}: {
  node: Node<NotationNodeData>;
  onUpdate: (id: string, patch: Partial<NotationNodeData>) => void;
  onUpdatePosition: (id: string, position: { x: number; y: number }) => void;
  onUpdatePosition3D: (id: string, position: Position3D) => void;
  onUpdateProperty: (id: string, propertyId: string, field: 'key' | 'value', value: string) => void;
  onAddProperty: (id: string) => void;
  onResetField: (
    id: string,
    field:
      | 'label'
      | 'shape'
      | 'imageUrl'
      | 'createdAt'
      | 'endedAt'
      | 'properties'
      | 'position'
      | 'position3d',
  ) => void;
  onError: (message: string) => void;
  metricMode: MetricMode;
  sharedMapCount: number;
}) {
  const metadata = nodeMetadata(toSemanticNode(node));
  return (
    <div className="inspector-section">
      <NodeSummaryCard
        metadata={metadata}
        metricMode={metricMode}
        sharedMapCount={sharedMapCount}
        nodeType={node.data.nodeType}
      />
      <label>
        <FieldHeader title="Label" onReset={() => onResetField(node.id, 'label')} />
        <textarea
          value={node.data.label}
          onChange={(event) => onUpdate(node.id, { label: event.target.value })}
        />
      </label>
      <label>
        <FieldHeader title="Shape" onReset={() => onResetField(node.id, 'shape')} />
        <select
          value={node.data.shape}
          onChange={(event) => onUpdate(node.id, { shape: event.target.value })}
        >
          {SHAPES.map((shape) => (
            <option key={shape} value={shape}>
              {shape}
            </option>
          ))}
        </select>
      </label>
      <label>
        <FieldHeader title="URL изображения" onReset={() => onResetField(node.id, 'imageUrl')} />
        <DraftInput
          value={node.data.imageUrl}
          onCommit={(imageUrl) => onUpdate(node.id, { imageUrl })}
        />
      </label>
      <label>
        Файл изображения
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) {
              return;
            }
            void readImageFile(file)
              .then((imageUrl) => onUpdate(node.id, { imageUrl }))
              .catch((fileError: Error) => onError(fileError.message));
          }}
        />
      </label>
      <label>
        <FieldHeader
          title="Начало актуальности (created_at)"
          onReset={() => onResetField(node.id, 'createdAt')}
        />
        <DraftInput
          value={node.data.createdAt}
          placeholder="2026-07-22T10:00:00Z"
          onCommit={(createdAt) => onUpdate(node.id, { createdAt })}
        />
      </label>
      <label>
        <FieldHeader
          title="Окончание актуальности (ended_at)"
          onReset={() => onResetField(node.id, 'endedAt')}
        />
        <DraftInput
          value={node.data.endedAt}
          placeholder="2026-12-31T18:00:00Z"
          onCommit={(endedAt) => onUpdate(node.id, { endedAt })}
        />
      </label>
      <div className="coordinate-editor">
        <FieldHeader title="2D coordinates" onReset={() => onResetField(node.id, 'position')} />
        <div className="coordinate-row">
          <label>
            X
            <CoordinateInput
              value={node.position.x}
              onCommit={(x) =>
                onUpdatePosition(node.id, {
                  x,
                  y: node.position.y,
                })
              }
            />
          </label>
          <label>
            Y
            <CoordinateInput
              value={node.position.y}
              onCommit={(y) =>
                onUpdatePosition(node.id, {
                  x: node.position.x,
                  y,
                })
              }
            />
          </label>
        </div>
      </div>
      <div className="coordinate-editor">
        <FieldHeader title="3D coordinates" onReset={() => onResetField(node.id, 'position3d')} />
        <div className="coordinate-row coordinate-row-3d">
          {(['x', 'y', 'z'] as const).map((axis) => (
            <label key={axis}>
              {axis.toUpperCase()}
              <CoordinateInput
                value={node.data.position3d[axis]}
                onCommit={(value) =>
                  onUpdatePosition3D(node.id, { ...node.data.position3d, [axis]: value })
                }
              />
            </label>
          ))}
        </div>
      </div>
      <PropertyEditor
        properties={node.data.properties}
        onChange={(propertyId, field, value) => onUpdateProperty(node.id, propertyId, field, value)}
        onAdd={() => onAddProperty(node.id)}
        onReset={() => onResetField(node.id, 'properties')}
      />
      <pre>{JSON.stringify(node.data.raw, null, 2)}</pre>
    </div>
  );
}

function NodeSummaryCard({
  metadata,
  metricMode,
  sharedMapCount,
  nodeType,
}: {
  metadata: NodeMetadata;
  metricMode: MetricMode;
  sharedMapCount: number;
  nodeType: string;
}) {
  const metric = metricValue(metadata, metricMode);
  const validity = validityPeriodLabel(metadata.createdAt, metadata.endedAt);
  const sourceIsUrl = /^https?:\/\//i.test(metadata.source);
  return (
    <section className="node-summary">
      <div className="node-summary-heading">
        <strong>Карточка узла</strong>
        <span>{nodeType}</span>
      </div>
      <dl>
        <dt>Статус</dt><dd><span className="status-value">{metadata.status || 'Не указан'}</span></dd>
        <dt>Регион</dt><dd>{metadata.region || 'Не указан'}</dd>
        <dt>Организация</dt><dd>{metadata.organization || 'Не указана'}</dd>
        <dt>Год</dt><dd>{metadata.year || 'Не указан'}</dd>
        <dt>Актуальность</dt><dd>{validity || 'Не указана'}</dd>
        <dt>{metricMode === 'planned' ? 'План' : 'Факт'}</dt><dd>{metric || 'Не указан'}</dd>
        <dt>Карты</dt><dd>{sharedMapCount}</dd>
      </dl>
      {metadata.description ? <p>{metadata.description}</p> : null}
      {metadata.source ? (
        <div className="node-source">
          <strong>Источник</strong>
          {sourceIsUrl
            ? <a href={metadata.source} target="_blank" rel="noreferrer">{metadata.source}</a>
            : <span>{metadata.source}</span>}
        </div>
      ) : null}
    </section>
  );
}

function EdgeEditor({
  edge,
  onUpdate,
  onUpdateProperty,
  onAddProperty,
  onResetField,
}: {
  edge: Edge<EditableEdgeData>;
  onUpdate: (id: string, patch: Partial<EditableEdgeData>) => void;
  onUpdateProperty: (id: string, propertyId: string, field: 'key' | 'value', value: string) => void;
  onAddProperty: (id: string) => void;
  onResetField: (id: string, field: 'label' | 'edgeType' | 'properties') => void;
}) {
  const currentEdgeType = edge.data?.edgeType || '';
  const edgeTypes = EDGE_TYPES.includes(currentEdgeType)
    ? EDGE_TYPES
    : [currentEdgeType, ...EDGE_TYPES].filter(Boolean);
  return (
    <div className="inspector-section">
      <label>
        <FieldHeader title="Label" onReset={() => onResetField(edge.id, 'label')} />
        <textarea
          value={edge.data?.label || ''}
          onChange={(event) => onUpdate(edge.id, { label: event.target.value })}
        />
      </label>
      <label>
        <FieldHeader title="Type" onReset={() => onResetField(edge.id, 'edgeType')} />
        <select
          value={edge.data?.edgeType || ''}
          onChange={(event) => onUpdate(edge.id, { edgeType: event.target.value })}
        >
          {edgeTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </label>
      <PropertyEditor
        properties={edge.data?.properties || []}
        onChange={(propertyId, field, value) => onUpdateProperty(edge.id, propertyId, field, value)}
        onAdd={() => onAddProperty(edge.id)}
        onReset={() => onResetField(edge.id, 'properties')}
      />
      <pre>{JSON.stringify(edge.data?.raw || {}, null, 2)}</pre>
    </div>
  );
}

function PropertyEditor({
  properties,
  onChange,
  onAdd,
  onReset,
}: {
  properties: EditableProperty[];
  onChange: (propertyId: string, field: 'key' | 'value', value: string) => void;
  onAdd: () => void;
  onReset: () => void;
}) {
  return (
    <div className="property-editor">
      <div className="property-editor-header">
        <strong>Properties</strong>
        <div className="property-actions">
          <button type="button" onClick={onReset}>
            Сброс
          </button>
          <button type="button" onClick={onAdd}>
            Добавить
          </button>
        </div>
      </div>
      {properties.map((property) => (
        <div className="property-row" key={property.id}>
          <input
            value={property.key}
            placeholder="key"
            onChange={(event) => onChange(property.id, 'key', event.target.value)}
          />
          <input
            value={property.value}
            placeholder="value"
            onChange={(event) => onChange(property.id, 'value', event.target.value)}
          />
        </div>
      ))}
    </div>
  );
}

function FieldHeader({ title, onReset }: { title: string; onReset: () => void }) {
  return (
    <span className="field-header">
      <span>{title}</span>
      <button type="button" onClick={onReset}>
        Сброс
      </button>
    </span>
  );
}

function DraftInput({
  value,
  onCommit,
  placeholder,
}: {
  value: string;
  onCommit: (value: string) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <input
      value={draft}
      placeholder={placeholder}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => onCommit(draft.trim())}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.currentTarget.blur();
        }
      }}
    />
  );
}

function CoordinateInput({
  value,
  onCommit,
}: {
  value: number;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(Math.round(value)));
  useEffect(() => setDraft(String(Math.round(value))), [value]);
  function commit() {
    const parsed = Number(draft);
    if (draft.trim() && Number.isFinite(parsed)) {
      onCommit(parsed);
    } else {
      setDraft(String(Math.round(value)));
    }
  }
  return (
    <input
      type="number"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.currentTarget.blur();
        }
      }}
    />
  );
}

function handleRequestError(
  error: Error,
  setAuthToken: (value: string) => void,
  setError: (value: string) => void,
  setSaveStatus?: (value: string) => void,
) {
  if (error.name === 'AbortError') {
    return;
  }
  setSaveStatus?.('');
  if (error instanceof AuthError) {
    setAuthToken('');
    setError('Неверный логин или пароль Graph API.');
    return;
  }
  setError(error.message);
}

function toReactFlow(payload: GraphPayload | null): {
  nodes: Node<NotationNodeData>[];
  edges: Edge<EditableEdgeData>[];
} {
  if (!payload) {
    return { nodes: [], edges: [] };
  }
  const graphNodes: Node<NotationNodeData>[] = payload.nodes.map((node) => {
    const base = nodeBase(node);
    return {
      id: node.id,
      type: 'notationNode',
      position: node.position,
      data: {
        label: node.label,
        shape: node.shape,
        nodeType: node.type,
        imageUrl: stringField(node.data.imageUrl || node.data.image_url),
        createdAt: stringField(node.data.created_at || node.data.createdAt),
        endedAt: stringField(node.data.ended_at || node.data.endedAt),
        position3d: position3DField(node.data.position3d, base.position3d),
        properties: propertiesFromUnknown(node.data.properties),
        annotationRevision: numberField(node.data.annotation_revision),
        base,
        style: node.style,
        raw: node.data,
      },
      draggable: true,
      zIndex: 2,
    };
  });

  if (payload.notation === 'use_case') {
    const boundaryLabel = payload.title || 'Система';
    graphNodes.unshift({
      id: '__system_boundary',
      type: 'systemBoundary',
      position: { x: -80, y: -120 },
      data: {
        label: boundaryLabel,
        shape: 'boundary',
        nodeType: 'boundary',
        imageUrl: '',
        createdAt: '',
        endedAt: '',
        position3d: { x: 0, y: 0, z: 0 },
        properties: [],
        annotationRevision: 0,
        base: {
          label: boundaryLabel,
          shape: 'boundary',
          imageUrl: '',
          createdAt: '',
          endedAt: '',
          position: { x: -80, y: -120 },
          position3d: { x: 0, y: 0, z: 0 },
          properties: [],
        },
        style: {},
        raw: {},
      },
      draggable: false,
      selectable: false,
      zIndex: 0,
      style: { width: 1580, height: 460 },
    });
  }

  const graphEdges: Edge<EditableEdgeData>[] = payload.edges.map((edge) => {
      const base = edgeBase(edge);
      const style = edgeStyle(edge);
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label,
        type: 'readable',
        animated: isAnimatedEdge(edge.type),
        data: {
          label: edge.label,
          edgeType: edge.type,
          showLabel: edgeLabelVisible(edge),
          properties: propertiesFromUnknown(edge.data.properties),
          annotationRevision: numberField(edge.data.annotation_revision),
          base,
          raw: edge.data,
        },
        style,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: String(style.stroke || '#64748b'),
          width: 16,
          height: 16,
        },
      };
    });
  return {
    nodes: graphNodes,
    edges: routeFlowEdges(graphEdges, graphNodes),
  };
}

function groupProjectionNode(group: GroupProjection): Node<NotationNodeData> {
  const position3d = {
    x: group.position.x / 3,
    y: -group.position.y / 3,
    z: 0,
  };
  const base: BaseNodeState = {
    label: group.title,
    shape: 'component',
    imageUrl: '',
    createdAt: '',
    endedAt: '',
    position: group.position,
    position3d,
    properties: [],
  };
  return {
    id: groupNodeId(group.groupId),
    type: 'graphGroup',
    position: group.position,
    data: {
      label: group.title,
      shape: 'component',
      nodeType: 'group',
      imageUrl: '',
      createdAt: '',
      endedAt: '',
      position3d,
      properties: [],
      annotationRevision: 0,
      base,
      style: {},
      raw: {
        groupId: group.groupId,
        collapsed: group.collapsed,
        memberCount: group.memberIds.length,
      },
    },
    draggable: false,
    selectable: group.collapsed,
    focusable: group.collapsed,
    zIndex: group.collapsed ? 4 : 0,
    style: {
      width: group.width,
      height: group.height,
      pointerEvents: group.collapsed ? 'auto' : 'none',
    },
  };
}

function GraphGroupNode({ data }: { data: NotationNodeData }) {
  const collapsed = Boolean(data.raw.collapsed);
  const memberCount = numberField(data.raw.memberCount);
  return (
    <div className={`graph-group-node${collapsed ? ' is-collapsed' : ''}`}>
      {collapsed ? <NodeHandles /> : null}
      <div className="graph-group-title">
        <strong>{data.label}</strong>
        <span>{memberCount} узл.</span>
      </div>
    </div>
  );
}

function NotationNode({ data }: { data: NotationNodeData }) {
  const nodeClass = `notation-node shape-${data.shape}${
    (data.sharedMapCount || 1) > 1 ? ' is-cross-map' : ''
  }`;
  const className = data.shape === 'diamond' ? `${nodeClass} has-rotated-content` : nodeClass;
  const meta = typeof data.raw.class === 'string' ? data.raw.class : data.nodeType;
  const validity = validityPeriodLabel(data.createdAt, data.endedAt);

  return (
    <div className={className} style={nodeInlineStyle(effectiveNodeStyle(data))}>
      <NodeHandles />
      {data.hasBranch ? (
        <button
          className="branch-toggle nodrag nopan"
          type="button"
          title={data.branchCollapsed ? 'Развернуть ветку' : 'Свернуть ветку'}
          aria-label={data.branchCollapsed ? 'Развернуть ветку' : 'Свернуть ветку'}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            data.onToggleBranch?.();
          }}
        >
          {data.branchCollapsed ? '+' : '−'}
        </button>
      ) : null}
      {(data.sharedMapCount || 1) > 1 ? (
        <span className="cross-map-badge" title="Узел присутствует в нескольких картах">
          {data.sharedMapCount}
        </span>
      ) : null}
      {data.shape === 'actor' ? <ActorNode label={data.label} imageUrl={data.imageUrl} /> : null}
      {data.shape !== 'actor' ? (
        <div className="node-content">
          <NodeImage imageUrl={data.imageUrl} />
          <div className="node-label">{data.label}</div>
          {data.shape !== 'class' ? <div className="node-meta">{meta}</div> : null}
          {data.shape === 'class' ? <ClassSections raw={data.raw} /> : null}
          {data.properties.length > 0 ? <NodeProperties properties={data.properties} /> : null}
          {validity ? <div className="node-time">{validity}</div> : null}
        </div>
      ) : null}
      {data.metricValue ? (
        <span className="node-metric">
          {data.metricMode === 'planned' ? 'План' : 'Факт'}: {data.metricValue}
        </span>
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
        className="node-handle node-handle-left"
        type="target"
        position={Position.Left}
      />
      <Handle
        id="left-source"
        className="node-handle node-handle-left"
        type="source"
        position={Position.Left}
      />
      <Handle
        id="right-source"
        className="node-handle node-handle-right"
        type="source"
        position={Position.Right}
      />
      <Handle
        id="right-target"
        className="node-handle node-handle-right"
        type="target"
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

function ActorNode({ label, imageUrl }: { label: string; imageUrl: string }) {
  return (
    <div className="actor-figure">
      {imageUrl ? (
        <NodeImage imageUrl={imageUrl} className="actor-node-image" />
      ) : (
        <span className="actor-head" />
      )}
      <span className="actor-body" />
      <span className="actor-arms" />
      <span className="actor-legs" />
      <div className="node-label">{label}</div>
    </div>
  );
}

function NodeImage({ imageUrl, className = 'node-image' }: { imageUrl: string; className?: string }) {
  if (!imageUrl) {
    return null;
  }
  return (
    <img
      key={imageUrl}
      className={className}
      src={imageUrl}
      alt=""
      referrerPolicy="no-referrer"
      onLoad={(event) => {
        event.currentTarget.hidden = false;
      }}
      onError={(event) => {
        event.currentTarget.hidden = true;
      }}
    />
  );
}

function ClassSections({ raw }: { raw: Record<string, unknown> }) {
  const explicitAttributes = Array.isArray(raw.attributes) ? raw.attributes.map(String) : [];
  const methods = Array.isArray(raw.methods) ? raw.methods.map(String) : [];
  const fallbackAttributes = Object.entries(raw)
    .filter(
      ([key]) =>
        ![
          'attributes',
          'methods',
          'annotation',
          'annotation_revision',
          'base',
          'properties',
          'imageUrl',
        ].includes(key),
    )
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

function NodeProperties({ properties }: { properties: EditableProperty[] }) {
  return (
    <div className="node-properties">
      {properties
        .filter((property) => property.key || property.value)
        .map((property) => (
          <span key={property.id}>
            {property.key}: {property.value}
          </span>
        ))}
    </div>
  );
}

function effectiveNodeStyle(data: NotationNodeData): Record<string, string | number> {
  const readiness = readinessPresentation(editablePropertyValue(data.properties, 'status'));
  return readiness
    ? {
        ...data.style,
        background: readiness.background,
        borderColor: readiness.borderColor,
        borderWidth: 3,
      }
    : data.style;
}

function editablePropertyValue(properties: EditableProperty[], key: string): string {
  const normalizedKey = key.toLocaleLowerCase();
  return properties.find((property) => property.key.toLocaleLowerCase() === normalizedKey)?.value
    || '';
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
    strokeWidth: Math.max(width, 2.1),
  };
}

function edgeLabelVisible(edge: GraphApiEdge): boolean {
  return !new Set(['found', 'from_source', 'source']).has(edge.type);
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

function newProperty(): EditableProperty {
  const id = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  return { id, key: '', value: '' };
}

function edgeData(edge: Edge<EditableEdgeData>): EditableEdgeData {
  const edgeType = String(edge.type || '');
  return (
    edge.data || {
      label: String(edge.label || ''),
      edgeType,
      properties: [],
      annotationRevision: 0,
      base: { label: String(edge.label || ''), edgeType, properties: [] },
      raw: {},
    }
  );
}

function nodeAnnotationPayload(node: Node<NotationNodeData>): Record<string, unknown> {
  return {
    label: node.data.label,
    shape: node.data.shape,
    imageUrl: node.data.imageUrl,
    createdAt: node.data.createdAt,
    endedAt: node.data.endedAt,
    properties: node.data.properties,
    position: {
      x: Math.round(node.position.x),
      y: Math.round(node.position.y),
    },
    position3d: node.data.position3d,
  };
}

function customNodePayload(node: Node<NotationNodeData>): GraphTemplateNode {
  return {
    id: node.id,
    label: node.data.label,
    type: node.data.nodeType,
    shape: node.data.shape,
    created_at: node.data.createdAt,
    ended_at: node.data.endedAt,
    x: Math.round(node.position.x),
    y: Math.round(node.position.y),
    position3d: node.data.position3d,
    image_data: node.data.imageUrl,
    properties: node.data.properties,
  };
}

function customEdgePayload(edge: Edge<EditableEdgeData>): GraphTemplateEdge {
  const data = edgeData(edge);
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: data.edgeType,
    label: data.label,
    properties: data.properties,
  };
}

function edgeAnnotationPayload(edge: Edge<EditableEdgeData>): Record<string, unknown> {
  const data = edgeData(edge);
  return {
    label: data.label,
    edgeType: data.edgeType,
    properties: data.properties,
  };
}

function nodeBase(node: GraphApiNode): BaseNodeState {
  const base = recordField(node.data.base);
  return {
    label: stringField(base.label) || node.label,
    shape: stringField(base.shape) || node.shape,
    imageUrl: stringField(base.imageUrl),
    createdAt: stringField(base.createdAt),
    endedAt: stringField(base.endedAt),
    position: positionField(base.position, node.position),
    position3d: position3DField(base.position3d, position3DField(node.data.position3d)),
    properties: propertiesFromUnknown(base.properties),
  };
}

function edgeBase(edge: GraphApiEdge): BaseEdgeState {
  const base = recordField(edge.data.base);
  return {
    label: stringField(base.label) || edge.label,
    edgeType: stringField(base.edgeType) || edge.type,
    properties: propertiesFromUnknown(base.properties),
  };
}

function propertiesFromUnknown(value: unknown): EditableProperty[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item, index) => {
    const property = recordField(item);
    return {
      id: stringField(property.id) || `property-${index}`,
      key: stringField(property.key),
      value: stringField(property.value),
    };
  });
}

function recordField(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function positionField(value: unknown, fallback: { x: number; y: number }): { x: number; y: number } {
  const position = recordField(value);
  const x = Number(position.x);
  const y = Number(position.y);
  return {
    x: Number.isFinite(x) ? x : fallback.x,
    y: Number.isFinite(y) ? y : fallback.y,
  };
}

function position3DField(
  value: unknown,
  fallback: Position3D = { x: 0, y: 0, z: 0 },
): Position3D {
  const position = recordField(value);
  return {
    x: finiteNumber(position.x, fallback.x),
    y: finiteNumber(position.y, fallback.y),
    z: finiteNumber(position.z, fallback.z),
  };
}

function finiteNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function validityPeriodLabel(createdAt: string, endedAt: string): string {
  const start = shortDateLabel(createdAt);
  const end = shortDateLabel(endedAt);
  if (start && end) {
    return start === end ? start : `${start} - ${end}`;
  }
  return start ? `с ${start}` : end ? `до ${end}` : '';
}

function shortDateLabel(value: string): string {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value.trim();
}

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function uniqueByType<T extends { type: string }>(entries: T[]): T[] {
  return [...new Map(entries.map((entry) => [entry.type, entry])).values()]
    .sort((left, right) => left.type.localeCompare(right.type));
}

function toSemanticNode(node: Node<NotationNodeData>): SemanticNode {
  return {
    id: node.id,
    label: node.data.label,
    nodeType: node.data.nodeType,
    createdAt: node.data.createdAt,
    endedAt: node.data.endedAt,
    properties: node.data.properties,
    raw: node.data.raw,
  };
}

function isNotation(value: string): value is Notation {
  return NOTATIONS.some((notation) => notation.value === value);
}

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function edgeTypeStyle(edgeType: string): CSSProperties {
  return EDGE_TYPE_STYLES[edgeType] || DEFAULT_EDGE_TYPE_STYLE;
}

function isAnimatedEdge(edgeType: string): boolean {
  return ANIMATED_EDGE_TYPES.has(edgeType);
}

function withEdgePresentation(
  edge: Edge<EditableEdgeData>,
  data: EditableEdgeData,
): Edge<EditableEdgeData> {
  const style = edgeTypeStyle(data.edgeType);
  return {
    ...edge,
    type: 'readable',
    label: data.label,
    animated: isAnimatedEdge(data.edgeType),
    data,
    style,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: String(style.stroke),
      width: 16,
      height: 16,
    },
  };
}

function routeFlowEdges(
  edges: Edge<EditableEdgeData>[],
  nodes: Node<NotationNodeData>[],
  orientation?: 'horizontal' | 'vertical',
): Edge<EditableEdgeData>[] {
  const positions = new Map(nodes.map((node) => [node.id, node.position]));
  const outgoing = groupEdges(edges, (edge) => edge.source);
  const incoming = groupEdges(edges, (edge) => edge.target);
  const parallel = groupEdges(edges, (edge) => `${edge.source}\u0000${edge.target}`);

  return edges.map((edge) => {
    const source = positions.get(edge.source) || { x: 0, y: 0 };
    const target = positions.get(edge.target) || { x: 0, y: 0 };
    const routeOrientation = orientation || inferOrientation(source, target);
    const sourceEdges = sortConnectedEdges(outgoing.get(edge.source) || [], positions, 'target', routeOrientation);
    const targetEdges = sortConnectedEdges(incoming.get(edge.target) || [], positions, 'source', routeOrientation);
    const pair = parallel.get(`${edge.source}\u0000${edge.target}`) || [edge];
    const handles = routeHandles(source, target, routeOrientation);
    return {
      ...edge,
      type: 'readable',
      sourceHandle: handles.source,
      targetHandle: handles.target,
      data: {
        ...edgeData(edge),
        parallelIndex: Math.max(0, pair.findIndex((item) => item.id === edge.id)),
        parallelTotal: pair.length,
        sourceOrder: Math.max(0, sourceEdges.findIndex((item) => item.id === edge.id)),
        targetOrder: Math.max(0, targetEdges.findIndex((item) => item.id === edge.id)),
      },
    };
  });
}

function groupEdges(
  edges: Edge<EditableEdgeData>[],
  key: (edge: Edge<EditableEdgeData>) => string,
): Map<string, Edge<EditableEdgeData>[]> {
  const groups = new Map<string, Edge<EditableEdgeData>[]>();
  edges.forEach((edge) => groups.set(key(edge), [...(groups.get(key(edge)) || []), edge]));
  return groups;
}

function sortConnectedEdges(
  edges: Edge<EditableEdgeData>[],
  positions: Map<string, { x: number; y: number }>,
  endpoint: 'source' | 'target',
  orientation: 'horizontal' | 'vertical',
): Edge<EditableEdgeData>[] {
  const axis = orientation === 'horizontal' ? 'y' : 'x';
  return [...edges].sort((left, right) => {
    const leftPosition = positions.get(left[endpoint]) || { x: 0, y: 0 };
    const rightPosition = positions.get(right[endpoint]) || { x: 0, y: 0 };
    return leftPosition[axis] - rightPosition[axis] || left.id.localeCompare(right.id);
  });
}

function inferOrientation(
  source: { x: number; y: number },
  target: { x: number; y: number },
): 'horizontal' | 'vertical' {
  return Math.abs(target.x - source.x) >= Math.abs(target.y - source.y)
    ? 'horizontal'
    : 'vertical';
}

function routeHandles(
  source: { x: number; y: number },
  target: { x: number; y: number },
  orientation: 'horizontal' | 'vertical',
): { source: string; target: string } {
  if (orientation === 'horizontal') {
    return target.x >= source.x
      ? { source: 'right-source', target: 'left-target' }
      : { source: 'left-source', target: 'right-target' };
  }
  return target.y >= source.y
    ? { source: 'bottom-source', target: 'top-target' }
    : { source: 'top-source', target: 'bottom-target' };
}

function arrangeNodes(
  nodes: Node<NotationNodeData>[],
  edges: Edge<EditableEdgeData>[],
  mode: LayoutMode,
): Node<NotationNodeData>[] {
  const fixed = nodes.filter((node) => node.id.startsWith('__'));
  const editable = nodes.filter((node) => !node.id.startsWith('__'));
  const positions = arrangeGraphNodes(
    editable.map((node) => ({
      id: node.id,
      createdAt: node.data.createdAt,
      nodeType: node.data.nodeType,
      position: node.position,
    })),
    edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      type: edgeData(edge).edgeType,
    })),
    mode,
  );
  return [
    ...fixed,
    ...editable.map((node) => ({
      ...node,
      position: positions.get(node.id) || node.position,
    })),
  ];
}

function templateDefinition(
  nodes: Node<NotationNodeData>[],
  edges: Edge<EditableEdgeData>[],
  groups: GraphGroupRecord[],
  includedNodeIds: Set<string>,
): GraphTemplateDefinition {
  const selectedNodes = nodes.filter((node) => includedNodeIds.has(node.id));
  const minX = Math.min(...selectedNodes.map((node) => node.position.x));
  const minY = Math.min(...selectedNodes.map((node) => node.position.y));
  const templateNodes = selectedNodes.map((node) => {
    const result = customNodePayload(node);
    return { ...result, x: result.x - minX, y: result.y - minY };
  });
  const templateEdges = edges
    .filter((edge) => includedNodeIds.has(edge.source) && includedNodeIds.has(edge.target))
    .map(customEdgePayload);
  const groupsById = new Map(groups.map((group) => [group.group_id, group]));
  const includedGroupIds = new Set(
    groups
      .filter((group) => {
        const memberIds = recursiveGroupNodeIds(group.group_id, groupsById);
        return memberIds.size > 0 && [...memberIds].every((nodeId) => includedNodeIds.has(nodeId));
      })
      .map((group) => group.group_id),
  );
  const templateGroups = groups
    .filter((group) => includedGroupIds.has(group.group_id))
    .map((group) => ({
      group_id: group.group_id,
      title: group.title,
      node_ids: group.node_ids,
      child_group_ids: group.child_group_ids.filter((id) => includedGroupIds.has(id)),
      collapsed: group.collapsed,
    }));
  return { nodes: templateNodes, edges: templateEdges, groups: templateGroups };
}

function childFirstGroups(groups: GraphTemplateGroup[]): GraphTemplateGroup[] {
  const groupsById = new Map(groups.map((group) => [group.group_id, group]));
  const result: GraphTemplateGroup[] = [];
  const visited = new Set<string>();
  const visit = (groupId: string) => {
    if (visited.has(groupId)) {
      return;
    }
    visited.add(groupId);
    const group = groupsById.get(groupId);
    if (!group) {
      return;
    }
    group.child_group_ids.forEach(visit);
    result.push(group);
  };
  groups.forEach((group) => visit(group.group_id));
  return result;
}

function uniqueId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID?.() || Date.now()}`;
}

function stringField(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function numberField(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function annotationKey(kind: 'node' | 'edge', id: string, notation: Notation): string {
  return `${notation}:${kind}:${id}`;
}

function readImageFile(file: File): Promise<string> {
  const supportedTypes = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
  if (!supportedTypes.has(file.type)) {
    return Promise.reject(new Error('Поддерживаются PNG, JPEG, WebP и GIF.'));
  }
  if (file.size > 700_000) {
    return Promise.reject(new Error('Размер изображения не должен превышать 700 КБ.'));
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Не удалось прочитать изображение.'));
    reader.readAsDataURL(file);
  });
}
