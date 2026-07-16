export type LayoutMode = 'overview' | 'follow' | 'timeline' | 'structure';

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
        mode === 'structure' ? 'vertical' : 'horizontal',
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
      position: {
        x: groupIndex * 380,
        y: (rowIndex - (group.length - 1) / 2) * 180,
      },
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
        ? { x: index * 360, y: 0 }
        : { x: (index % 4) * 300, y: Math.floor(index / 4) * 210 },
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
    if (
      source === undefined
      || target === undefined
      || source === target
      || adjacency[source].has(target)
    ) {
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
  const componentsByLevel = orderedComponentsByLevel(components, adjacency, levels);
  const maxLevel = Math.max(...levels);
  const positioned: LayoutNode[] = [];
  [...componentsByLevel.entries()].forEach(([level, componentIndexes]) => {
    const nodeIds = componentIndexes.flatMap((componentIndex) =>
      [...components[componentIndex]].sort(),
    );
    nodeIds.forEach((nodeId, index) => {
      const node = byId.get(nodeId);
      if (!node) {
        return;
      }
      const crossAxis = (index - (nodeIds.length - 1) / 2) * 160;
      const mainAxis = (level - maxLevel / 2) * (direction === 'horizontal' ? 320 : 210);
      positioned.push({
        ...node,
        position: {
          x: Math.round(direction === 'horizontal' ? mainAxis : crossAxis * 1.45),
          y: Math.round(direction === 'horizontal' ? crossAxis : mainAxis),
        },
      });
    });
  });
  return positioned;
}

function orderedComponentsByLevel(
  components: string[][],
  adjacency: Set<number>[],
  levels: number[],
): Map<number, number[]> {
  const byLevel = new Map<number, number[]>();
  levels.forEach((level, index) => {
    byLevel.set(level, [...(byLevel.get(level) || []), index]);
  });
  for (const indexes of byLevel.values()) {
    indexes.sort((left, right) =>
      componentKey(components[left]).localeCompare(componentKey(components[right])),
    );
  }
  const predecessors = components.map(() => new Set<number>());
  adjacency.forEach((targets, source) =>
    targets.forEach((target) => predecessors[target].add(source)),
  );
  const maxLevel = Math.max(...levels);
  for (let pass = 0; pass < 4; pass += 1) {
    for (let level = 1; level <= maxLevel; level += 1) {
      sortByNeighbors(byLevel, level, predecessors);
    }
    for (let level = maxLevel - 1; level >= 0; level -= 1) {
      sortByNeighbors(byLevel, level, adjacency);
    }
  }
  return byLevel;
}

function sortByNeighbors(
  levels: Map<number, number[]>,
  level: number,
  neighbors: Set<number>[],
): void {
  const current = levels.get(level);
  if (!current || current.length < 2) {
    return;
  }
  const positions = new Map<number, number>();
  for (const indexes of levels.values()) {
    indexes.forEach((component, index) => positions.set(component, index));
  }
  current.sort(
    (left, right) =>
      barycenter(left, neighbors, positions) - barycenter(right, neighbors, positions),
  );
}

function barycenter(
  component: number,
  neighbors: Set<number>[],
  positions: Map<number, number>,
): number {
  const values = [...neighbors[component]].map((neighbor) => positions.get(neighbor) || 0);
  return values.length > 0
    ? values.reduce((total, value) => total + value, 0) / values.length
    : positions.get(component) || 0;
}

function componentKey(component: string[]): string {
  return [...component].sort().join('\u0000');
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
