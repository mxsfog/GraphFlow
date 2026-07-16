import type { GraphGroupRecord } from './graphApiClient.js';

export type WorkspaceNode = {
  id: string;
  position: { x: number; y: number };
  width?: number;
  height?: number;
};

export type WorkspaceEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
};

export type GroupProjection = {
  id: string;
  groupId: string;
  title: string;
  collapsed: boolean;
  memberIds: string[];
  position: { x: number; y: number };
  width: number;
  height: number;
};

export type ProjectedEdge = WorkspaceEdge & {
  sourceEdgeIds: string[];
  count: number;
};

export type WorkspaceProjection = {
  groups: GroupProjection[];
  hiddenNodeIds: Set<string>;
  edges: ProjectedEdge[];
};

const GROUP_PREFIX = '__group:';
const DEFAULT_NODE_WIDTH = 220;
const DEFAULT_NODE_HEIGHT = 100;
const GROUP_PADDING = 40;

export function projectWorkspace(
  nodes: WorkspaceNode[],
  edges: WorkspaceEdge[],
  groups: GraphGroupRecord[],
): WorkspaceProjection {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const groupById = new Map(groups.map((group) => [group.group_id, group]));
  const parentByGroup = groupParents(groups);
  const collapsedOwners = new Map<string, string>();

  for (const group of groups) {
    if (!group.collapsed || hasCollapsedAncestor(group.group_id, parentByGroup, groupById)) {
      continue;
    }
    for (const nodeId of recursiveGroupNodeIds(group.group_id, groupById)) {
      if (nodeById.has(nodeId)) {
        collapsedOwners.set(nodeId, group.group_id);
      }
    }
  }

  const projections = groups.flatMap((group) => {
    if (hasCollapsedAncestor(group.group_id, parentByGroup, groupById)) {
      return [];
    }
    const memberIds = [...recursiveGroupNodeIds(group.group_id, groupById)].filter((nodeId) =>
      nodeById.has(nodeId),
    );
    if (memberIds.length === 0) {
      return [];
    }
    const bounds = groupBounds(memberIds.map((nodeId) => nodeById.get(nodeId)!));
    const width = group.collapsed ? DEFAULT_NODE_WIDTH : bounds.width + GROUP_PADDING * 2;
    const height = group.collapsed ? 82 : bounds.height + GROUP_PADDING * 2;
    return [{
      id: groupNodeId(group.group_id),
      groupId: group.group_id,
      title: group.title,
      collapsed: group.collapsed,
      memberIds,
      position: group.collapsed
        ? {
            x: bounds.x + bounds.width / 2 - width / 2,
            y: bounds.y + bounds.height / 2 - height / 2,
          }
        : { x: bounds.x - GROUP_PADDING, y: bounds.y - GROUP_PADDING },
      width,
      height,
    }];
  });

  return {
    groups: projections,
    hiddenNodeIds: new Set(collapsedOwners.keys()),
    edges: projectEdges(edges, collapsedOwners),
  };
}

export function recursiveGroupNodeIds(
  groupId: string,
  groups: Map<string, Pick<GraphGroupRecord, 'node_ids' | 'child_group_ids'>>,
): Set<string> {
  const result = new Set<string>();
  const visited = new Set<string>();
  const visit = (currentId: string) => {
    if (visited.has(currentId)) {
      return;
    }
    visited.add(currentId);
    const group = groups.get(currentId);
    if (!group) {
      return;
    }
    group.node_ids.forEach((nodeId) => result.add(nodeId));
    group.child_group_ids.forEach(visit);
  };
  visit(groupId);
  return result;
}

export function descendantNodeIds(
  rootId: string,
  edges: WorkspaceEdge[],
  edgeTypes: ReadonlySet<string>,
): string[] {
  const targetsBySource = new Map<string, string[]>();
  for (const edge of edges) {
    if (!edgeTypes.has(edge.type)) {
      continue;
    }
    const targets = targetsBySource.get(edge.source) || [];
    targets.push(edge.target);
    targetsBySource.set(edge.source, targets);
  }
  const visited = new Set([rootId]);
  const queue = [...(targetsBySource.get(rootId) || [])];
  const descendants: string[] = [];
  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    if (visited.has(nodeId)) {
      continue;
    }
    visited.add(nodeId);
    descendants.push(nodeId);
    queue.push(...(targetsBySource.get(nodeId) || []));
  }
  return descendants;
}

export function groupNodeId(groupId: string): string {
  return `${GROUP_PREFIX}${groupId}`;
}

export function groupIdFromNode(nodeId: string): string | null {
  return nodeId.startsWith(GROUP_PREFIX) ? nodeId.slice(GROUP_PREFIX.length) : null;
}

function projectEdges(
  edges: WorkspaceEdge[],
  collapsedOwners: Map<string, string>,
): ProjectedEdge[] {
  const projected = new Map<string, ProjectedEdge>();
  for (const edge of edges) {
    const source = collapsedOwners.has(edge.source)
      ? groupNodeId(collapsedOwners.get(edge.source)!)
      : edge.source;
    const target = collapsedOwners.has(edge.target)
      ? groupNodeId(collapsedOwners.get(edge.target)!)
      : edge.target;
    if (source === target) {
      continue;
    }
    const key = `${source}\u0000${target}\u0000${edge.type}`;
    const existing = projected.get(key);
    if (existing) {
      existing.sourceEdgeIds.push(edge.id);
      existing.count += 1;
      existing.label = `${edge.type} · ${existing.count}`;
      continue;
    }
    projected.set(key, {
      ...edge,
      id: source === edge.source && target === edge.target
        ? edge.id
        : `__group-edge:${stableKey(key)}`,
      source,
      target,
      sourceEdgeIds: [edge.id],
      count: 1,
    });
  }
  return [...projected.values()];
}

function groupParents(groups: GraphGroupRecord[]): Map<string, string> {
  const result = new Map<string, string>();
  for (const group of groups) {
    group.child_group_ids.forEach((childId) => result.set(childId, group.group_id));
  }
  return result;
}

function hasCollapsedAncestor(
  groupId: string,
  parentByGroup: Map<string, string>,
  groupById: Map<string, GraphGroupRecord>,
): boolean {
  const visited = new Set<string>();
  let parentId = parentByGroup.get(groupId);
  while (parentId && !visited.has(parentId)) {
    if (groupById.get(parentId)?.collapsed) {
      return true;
    }
    visited.add(parentId);
    parentId = parentByGroup.get(parentId);
  }
  return false;
}

function groupBounds(nodes: WorkspaceNode[]): { x: number; y: number; width: number; height: number } {
  const left = Math.min(...nodes.map((node) => node.position.x));
  const top = Math.min(...nodes.map((node) => node.position.y));
  const right = Math.max(
    ...nodes.map((node) => node.position.x + (node.width || DEFAULT_NODE_WIDTH)),
  );
  const bottom = Math.max(
    ...nodes.map((node) => node.position.y + (node.height || DEFAULT_NODE_HEIGHT)),
  );
  return { x: left, y: top, width: right - left, height: bottom - top };
}

function stableKey(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}
