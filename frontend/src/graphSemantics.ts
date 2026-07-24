import { stronglyConnectedComponents, type LayoutEdge } from './graphLayout.js';

export type GraphProperty = {
  key: string;
  value: string;
};

export type SemanticNode = {
  id: string;
  label: string;
  nodeType: string;
  createdAt: string;
  endedAt: string;
  properties: GraphProperty[];
  raw: Record<string, unknown>;
};

export type SemanticEdge = LayoutEdge;
export type MetricMode = 'planned' | 'actual';

export type AttributeFilters = {
  status: string;
  region: string;
  organization: string;
  direction: string;
  year: string;
};

export type NodeMetadata = AttributeFilters & {
  description: string;
  source: string;
  planned: string;
  actual: string;
  createdAt: string;
  endedAt: string;
};

export type AttributeOptions = Record<keyof AttributeFilters, string[]>;

export const EMPTY_ATTRIBUTE_FILTERS: AttributeFilters = {
  status: '',
  region: '',
  organization: '',
  direction: '',
  year: '',
};

export const HIERARCHY_EDGE_TYPES = new Set([
  'contains',
  'include',
  'properties',
  'todo',
  'has_block',
  'has_process',
  'uses_technology',
  'has_goal',
  'has_indicator',
  'has_activity',
  'has_project',
  'produces_result',
]);

const FIELD_ALIASES: Record<keyof NodeMetadata, string[]> = {
  status: ['status', 'статус'],
  region: ['region', 'регион', 'territory', 'территория'],
  organization: [
    'organization',
    'organisation',
    'org',
    'owner',
    'responsible',
    'организация',
    'исполнитель',
    'ответственный',
  ],
  direction: ['direction', 'направление', 'map', 'карта'],
  year: ['year', 'год'],
  description: ['description', 'summary', 'reason', 'описание', 'обоснование'],
  source: ['source', 'url', 'domain', 'источник', 'ссылка'],
  planned: [
    'planned',
    'plan',
    'plannedvalue',
    'target',
    'план',
    'плановоезначение',
  ],
  actual: [
    'actual',
    'fact',
    'actualvalue',
    'факт',
    'фактическоезначение',
  ],
  createdAt: ['created_at', 'createdat', 'started_at', 'start_date', 'начало', 'датаначала'],
  endedAt: ['ended_at', 'endedat', 'finished_at', 'end_date', 'окончание', 'датаокончания'],
};

export function nodeMetadata(node: SemanticNode): NodeMetadata {
  const propertyValues = new Map(
    node.properties
      .map((property) => [normalizeKey(property.key), String(property.value || '').trim()] as const)
      .filter(([key, value]) => key && value),
  );
  const rawValues = new Map(
    Object.entries(node.raw)
      .map(([key, value]) => [normalizeKey(key), scalarValue(value)] as const)
      .filter(([key, value]) => key && value),
  );
  const field = (name: keyof NodeMetadata) => firstAliasValue(
    FIELD_ALIASES[name],
    propertyValues,
    rawValues,
  );
  const createdAt = field('createdAt') || node.createdAt;
  const endedAt = field('endedAt') || node.endedAt;
  const year = field('year') || yearFromDate(createdAt);
  const organization = field('organization')
    || (node.nodeType === 'organization' ? node.label.trim() : '');
  return {
    status: field('status'),
    region: field('region'),
    organization,
    direction: field('direction'),
    year,
    description: field('description'),
    source: field('source'),
    planned: field('planned'),
    actual: field('actual'),
    createdAt,
    endedAt,
  };
}

export function attributeOptions(nodes: SemanticNode[]): AttributeOptions {
  const metadata = nodes.map(nodeMetadata);
  return {
    status: uniqueValues(metadata.map((item) => item.status)),
    region: uniqueValues(metadata.map((item) => item.region)),
    organization: uniqueValues(metadata.map((item) => item.organization)),
    direction: uniqueValues(
      metadata.flatMap((item) => item.direction.split(';').map((value) => value.trim())),
    ),
    year: uniqueValues(metadata.flatMap(validityYears)),
  };
}

export function matchesAttributeFilters(node: SemanticNode, filters: AttributeFilters): boolean {
  const metadata = nodeMetadata(node);
  return (!filters.status || metadata.status === filters.status)
    && (!filters.region || metadata.region === filters.region)
    && (!filters.organization || metadata.organization === filters.organization)
    && (
      !filters.direction
      || metadata.direction
        .split(';')
        .map((value) => value.trim())
        .includes(filters.direction)
    )
    && (!filters.year || validityYears(metadata).includes(filters.year));
}

export type ReadinessPresentation = {
  level: 'green' | 'orange' | 'red';
  label: string;
  background: string;
  borderColor: string;
};

const READINESS_PRESENTATIONS: ReadinessPresentation[] = [
  {
    level: 'green',
    label: 'Зелёный: применяется в РФ',
    background: '#dcfce7',
    borderColor: '#15803d',
  },
  {
    level: 'orange',
    label: 'Оранжевый: есть ограничения',
    background: '#ffedd5',
    borderColor: '#c2410c',
  },
  {
    level: 'red',
    label: 'Красный: отсутствует в РФ',
    background: '#fee2e2',
    borderColor: '#b91c1c',
  },
];

export function readinessPresentation(status: string): ReadinessPresentation | null {
  const normalized = status.toLocaleLowerCase().replaceAll('ё', 'е');
  if (normalized.includes('красн') || /\bred\b/.test(normalized)) {
    return READINESS_PRESENTATIONS[2];
  }
  if (normalized.includes('оранж') || /\borange\b/.test(normalized)) {
    return READINESS_PRESENTATIONS[1];
  }
  if (normalized.includes('зелен') || /\bgreen\b/.test(normalized)) {
    return READINESS_PRESENTATIONS[0];
  }
  return null;
}

export function hierarchyLevels(
  nodes: Array<Pick<SemanticNode, 'id'>>,
  edges: SemanticEdge[],
): Map<string, number> {
  const nodeIds = nodes.map((node) => node.id);
  const nodeIdSet = new Set(nodeIds);
  const relevantEdges = hierarchyEdges(edges).filter(
    (edge) => nodeIdSet.has(edge.source) && nodeIdSet.has(edge.target),
  );
  if (nodeIds.length === 0) {
    return new Map();
  }
  if (relevantEdges.length === 0) {
    return new Map(nodeIds.map((id) => [id, 0]));
  }
  const components = stronglyConnectedComponents(nodeIds, relevantEdges);
  const componentByNode = new Map<string, number>();
  components.forEach((component, index) =>
    component.forEach((nodeId) => componentByNode.set(nodeId, index)),
  );
  const adjacency = components.map(() => new Set<number>());
  const indegree = components.map(() => 0);
  relevantEdges.forEach((edge) => {
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
  return new Map(
    components.flatMap((component, index) => component.map((nodeId) => [nodeId, levels[index]])),
  );
}

export function branchRoots(edges: SemanticEdge[]): Set<string> {
  return new Set(hierarchyEdges(edges).map((edge) => edge.source));
}

export function hiddenBranchNodeIds(
  collapsedRootIds: ReadonlySet<string>,
  edges: SemanticEdge[],
): Set<string> {
  const targetsBySource = new Map<string, string[]>();
  hierarchyEdges(edges).forEach((edge) => {
    targetsBySource.set(edge.source, [...(targetsBySource.get(edge.source) || []), edge.target]);
  });
  const hidden = new Set<string>();
  collapsedRootIds.forEach((rootId) => {
    const visited = new Set([rootId]);
    const queue = [...(targetsBySource.get(rootId) || [])];
    while (queue.length > 0) {
      const current = queue.shift()!;
      if (visited.has(current)) {
        continue;
      }
      visited.add(current);
      hidden.add(current);
      queue.push(...(targetsBySource.get(current) || []));
    }
  });
  return hidden;
}

export function canonicalNodeLabel(value: string): string {
  return value.normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, ' ').trim();
}

export function metricValue(metadata: NodeMetadata, mode: MetricMode): string {
  return mode === 'planned' ? metadata.planned : metadata.actual;
}

function hierarchyEdges(edges: SemanticEdge[]): SemanticEdge[] {
  const selected = edges.filter((edge) => HIERARCHY_EDGE_TYPES.has(edge.type));
  return selected.length > 0 ? selected : edges;
}

function normalizeKey(value: string): string {
  return value.normalize('NFKC').toLocaleLowerCase().replace(/[\s_.-]+/g, '').trim();
}

function scalarValue(value: unknown): string {
  return ['string', 'number', 'boolean'].includes(typeof value) ? String(value).trim() : '';
}

function firstAliasValue(
  aliases: string[],
  propertyValues: Map<string, string>,
  rawValues: Map<string, string>,
): string {
  for (const alias of aliases.map(normalizeKey)) {
    const value = propertyValues.get(alias) || rawValues.get(alias);
    if (value) {
      return value;
    }
  }
  return '';
}

function yearFromDate(value: string): string {
  const match = value.match(/(?:^|\D)((?:19|20)\d{2})(?:\D|$)/);
  return match?.[1] || '';
}

function validityYears(metadata: NodeMetadata): string[] {
  const values = new Set(metadata.year ? [metadata.year] : []);
  const start = Number(yearFromDate(metadata.createdAt));
  const end = Number(yearFromDate(metadata.endedAt));
  if (start) {
    values.add(String(start));
  }
  if (end) {
    values.add(String(end));
  }
  if (start && end && end >= start && end - start <= 200) {
    for (let year = start; year <= end; year += 1) {
      values.add(String(year));
    }
  }
  return [...values];
}

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((left, right) =>
    left.localeCompare(right, 'ru', { numeric: true }),
  );
}
