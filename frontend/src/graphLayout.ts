export type LayoutMode = 'follow' | 'timeline' | 'structure';

export type LayoutNode = {
  id: string;
  createdAt: string;
  nodeType: string;
  position: { x: number; y: number };
};

export type LayoutEdge = {
  source: string;
  target: string;
  type: string;
};

export function arrangeGraphNodes(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  mode: LayoutMode,
): Map<string, { x: number; y: number }> {
  const positioned = mode === 'timeline'
    ? timelineLayout(nodes)
    : layeredLayout(
        nodes,
        mode === 'follow' ? edges.filter((edge) => edge.type === 'follow') : edges,
        mode === 'follow' ? 'horizontal' : 'vertical',
      );
  return new Map(positioned.map((node) => [node.id, node.position]));
}

function timelineLayout(nodes: LayoutNode[]): LayoutNode[] {
  const groups = new Map<string, LayoutNode[]>();
  [...nodes].sort(compareByCreatedAt).forEach((node) => {
    const timestamp = parseCreatedAt(node.createdAt);
    const key = timestamp === Number.MAX_SAFE_INTEGER
      ? 'Без даты'
      : new Date(timestamp).toISOString().slice(0, 10);
    groups.set(key, [...(groups.get(key) || []), node]);
  });
  return [...groups.values()].flatMap((group, groupIndex) =>
    group.map((node, rowIndex) => ({
      ...node,
      position: { x: -620 + groupIndex * 320, y: -180 + rowIndex * 180 },
    })),
  );
}

function layeredLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  direction: 'horizontal' | 'vertical',
): LayoutNode[] {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const graphEdges = edges.filter(
    (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
  );
  if (graphEdges.length === 0) {
    return [...nodes].sort(compareByStructure).map((node, index) => ({
      ...node,
      position: direction === 'horizontal'
        ? { x: -620 + index * 300, y: -100 }
        : { x: -300 + (index % 4) * 300, y: -180 + Math.floor(index / 4) * 190 },
    }));
  }
  const components = stronglyConnectedComponents([...nodeIds], graphEdges);
  const componentByNode = new Map<string, number>();
  components.forEach((component, index) =>
    component.forEach((nodeId) => componentByNode.set(nodeId, index)),
  );
  const adjacency = components.map(() => new Set<number>());
  const indegree = components.map(() => 0);
  graphEdges.forEach((edge) => {
    const source = componentByNode.get(edge.source);
    const target = componentByNode.get(edge.target);
    if (source === undefined || target === undefined || source === target || adjacency[source].has(target)) {
      return;
    }
    adjacency[source].add(target);
    indegree[target] += 1;
  });
  const queue = indegree.flatMap((value, index) => (value === 0 ? [index] : []));
  const levels = components.map(() => 0);
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const source = queue[cursor];
    adjacency[source].forEach((target) => {
      levels[target] = Math.max(levels[target], levels[source] + 1);
      indegree[target] -= 1;
      if (indegree[target] === 0) {
        queue.push(target);
      }
    });
  }
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const componentsByLevel = new Map<number, number[]>();
  levels.forEach((level, index) => {
    componentsByLevel.set(level, [...(componentsByLevel.get(level) || []), index]);
  });
  const positioned: LayoutNode[] = [];
  [...componentsByLevel.entries()].forEach(([level, componentIndexes]) => {
    componentIndexes.forEach((componentIndex, groupIndex) => {
      const component = components[componentIndex];
      const center = direction === 'horizontal'
        ? { x: -620 + level * 340, y: -180 + groupIndex * 240 }
        : { x: -620 + groupIndex * 320, y: -180 + level * 220 };
      component.forEach((nodeId, cycleIndex) => {
        const node = byId.get(nodeId);
        if (!node) {
          return;
        }
        const angle = component.length > 1 ? (2 * Math.PI * cycleIndex) / component.length : 0;
        const radius = component.length > 1 ? 90 : 0;
        positioned.push({
          ...node,
          position: {
            x: Math.round(center.x + Math.cos(angle) * radius),
            y: Math.round(center.y + Math.sin(angle) * radius),
          },
        });
      });
    });
  });
  return positioned;
}

function compareByCreatedAt(left: LayoutNode, right: LayoutNode): number {
  return parseCreatedAt(left.createdAt) - parseCreatedAt(right.createdAt)
    || left.id.localeCompare(right.id);
}

function compareByStructure(left: LayoutNode, right: LayoutNode): number {
  return structureLevel(left.nodeType) - structureLevel(right.nodeType)
    || left.id.localeCompare(right.id);
}

function structureLevel(nodeType: string): number {
  const order = ['actor', 'process', 'section', 'task', 'component', 'model', 'news', 'topic', 'source', 'storage', 'result'];
  const index = order.indexOf(nodeType);
  return index >= 0 ? index : order.length;
}

export function parseCreatedAt(value: string): number {
  const normalized = value.includes(' ') && !value.includes('T') ? value.replace(' ', 'T') : value;
  const timestamp = Date.parse(normalized);
  return Number.isFinite(timestamp) ? timestamp : Number.MAX_SAFE_INTEGER;
}

export function stronglyConnectedComponents(nodeIds: string[], edges: LayoutEdge[]): string[][] {
  const adjacency = new Map(nodeIds.map((nodeId) => [nodeId, [] as string[]]));
  edges.forEach((edge) => adjacency.get(edge.source)?.push(edge.target));
  const indexes = new Map<string, number>();
  const lowLinks = new Map<string, number>();
  const stack: string[] = [];
  const onStack = new Set<string>();
  const components: string[][] = [];
  let index = 0;

  function connect(nodeId: string) {
    indexes.set(nodeId, index);
    lowLinks.set(nodeId, index);
    index += 1;
    stack.push(nodeId);
    onStack.add(nodeId);
    (adjacency.get(nodeId) || []).forEach((target) => {
      if (!indexes.has(target)) {
        connect(target);
        lowLinks.set(nodeId, Math.min(lowLinks.get(nodeId) || 0, lowLinks.get(target) || 0));
      } else if (onStack.has(target)) {
        lowLinks.set(nodeId, Math.min(lowLinks.get(nodeId) || 0, indexes.get(target) || 0));
      }
    });
    if (lowLinks.get(nodeId) !== indexes.get(nodeId)) {
      return;
    }
    const component: string[] = [];
    while (stack.length > 0) {
      const current = stack.pop() as string;
      onStack.delete(current);
      component.push(current);
      if (current === nodeId) {
        break;
      }
    }
    components.push(component);
  }

  nodeIds.forEach((nodeId) => {
    if (!indexes.has(nodeId)) {
      connect(nodeId);
    }
  });
  return components;
}
