export type AnnotationPayload = {
  graph_id: string;
  notation: string;
  element_id: string;
  element_kind: 'node' | 'edge';
  revision: number;
  payload: Record<string, unknown>;
};

export type AnnotationResult = {
  element_id: string;
  element_kind: 'node' | 'edge';
  revision: number;
};

export type GraphGroupRecord = {
  graph_id: string;
  notation: string;
  group_id: string;
  title: string;
  node_ids: string[];
  child_group_ids: string[];
  collapsed: boolean;
  revision: number;
  created_at: string;
  updated_at: string;
};

export type GraphTemplateNode = {
  id: string;
  label: string;
  type: string;
  shape: string;
  created_at: string;
  ended_at: string;
  x: number;
  y: number;
  position3d: { x: number; y: number; z: number };
  image_data: string;
  properties: unknown[];
};

export type GraphTemplateEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  properties: unknown[];
};

export type GraphTemplateGroup = {
  group_id: string;
  title: string;
  node_ids: string[];
  child_group_ids: string[];
  collapsed: boolean;
};

export type GraphTemplateDefinition = {
  nodes: GraphTemplateNode[];
  edges: GraphTemplateEdge[];
  groups: GraphTemplateGroup[];
};

export type GraphTemplateRecord = {
  template_id: string;
  name: string;
  description: string;
  notation: string;
  revision: number;
  created_at: string;
  updated_at: string;
  definition?: GraphTemplateDefinition;
};

export type GraphViewState = {
  notation: string;
  view_mode: '2d' | '3d';
  metric_mode: 'planned' | 'actual';
  inverted_background: boolean;
  hidden_node_types: string[];
  hidden_edge_types: string[];
  hidden_levels: number[];
  attribute_filters: {
    status: string;
    region: string;
    organization: string;
    year: string;
  };
  collapsed_branches: string[];
  viewport: { x: number; y: number; zoom: number } | Record<string, never>;
};

export type GraphViewRecord = {
  graph_id: string;
  view_id: string;
  name: string;
  state: GraphViewState;
  revision: number;
  created_at: string;
  updated_at: string;
};

export type NodeOccurrence = {
  key: string;
  label: string;
  map_count: number;
  map_ids: string[];
};

export class AuthError extends Error {
  constructor() {
    super('Graph API authentication failed');
    this.name = 'AuthError';
  }
}

export function encodeBasicAuth(username: string, password: string): string {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return window.btoa(binary);
}

export function loadJson<T>(url: string, signal: AbortSignal, authToken: string): Promise<T> {
  return requestJson<T>(url, authToken, { signal });
}

export function saveAnnotation(
  apiBaseUrl: string,
  authToken: string,
  payload: AnnotationPayload,
): Promise<{ revision: number }> {
  return postJson(`${apiBaseUrl}/api/graph/annotations`, authToken, payload);
}

export function saveAnnotationsBatch(
  apiBaseUrl: string,
  authToken: string,
  items: AnnotationPayload[],
): Promise<{ items: AnnotationResult[] }> {
  return postJson(`${apiBaseUrl}/api/graph/annotations/batch`, authToken, { items });
}

export async function saveCustomGraphDefinition(
  apiBaseUrl: string,
  authToken: string,
  payload: Record<string, unknown>,
): Promise<void> {
  await postJson(`${apiBaseUrl}/api/graphs`, authToken, payload);
}

export function loadGraphGroups(
  apiBaseUrl: string,
  authToken: string,
  graphId: string,
  notation: string,
  signal: AbortSignal,
): Promise<{ groups: GraphGroupRecord[] }> {
  const query = new URLSearchParams({ graph_id: graphId, notation });
  return loadJson(`${apiBaseUrl}/api/graph/groups?${query}`, signal, authToken);
}

export function saveGraphGroup(
  apiBaseUrl: string,
  authToken: string,
  payload: Omit<GraphGroupRecord, 'created_at' | 'updated_at'>,
): Promise<GraphGroupRecord & { saved: boolean }> {
  return postJson(`${apiBaseUrl}/api/graph/groups`, authToken, payload);
}

export function deleteGraphGroup(
  apiBaseUrl: string,
  authToken: string,
  graphId: string,
  notation: string,
  groupId: string,
): Promise<{ deleted: boolean; group_id: string }> {
  const query = new URLSearchParams({ graph_id: graphId, notation });
  return deleteJson(
    `${apiBaseUrl}/api/graph/groups/${encodeURIComponent(groupId)}?${query}`,
    authToken,
  );
}

export function loadGraphTemplates(
  apiBaseUrl: string,
  authToken: string,
  signal: AbortSignal,
): Promise<{ templates: GraphTemplateRecord[] }> {
  return loadJson(`${apiBaseUrl}/api/graph/templates`, signal, authToken);
}

export function loadGraphTemplate(
  apiBaseUrl: string,
  authToken: string,
  templateId: string,
  signal: AbortSignal,
): Promise<GraphTemplateRecord & { definition: GraphTemplateDefinition }> {
  return loadJson(
    `${apiBaseUrl}/api/graph/templates/${encodeURIComponent(templateId)}`,
    signal,
    authToken,
  );
}

export function saveGraphTemplate(
  apiBaseUrl: string,
  authToken: string,
  payload: {
    template_id: string;
    name: string;
    description: string;
    notation: string;
    revision: number;
    definition: GraphTemplateDefinition;
  },
): Promise<GraphTemplateRecord & { saved: boolean; definition: GraphTemplateDefinition }> {
  return postJson(`${apiBaseUrl}/api/graph/templates`, authToken, payload);
}

export function deleteGraphTemplate(
  apiBaseUrl: string,
  authToken: string,
  templateId: string,
): Promise<{ deleted: boolean; template_id: string }> {
  return deleteJson(
    `${apiBaseUrl}/api/graph/templates/${encodeURIComponent(templateId)}`,
    authToken,
  );
}

export function loadGraphViews(
  apiBaseUrl: string,
  authToken: string,
  graphId: string,
  signal: AbortSignal,
): Promise<{ views: GraphViewRecord[] }> {
  const query = new URLSearchParams({ graph_id: graphId });
  return loadJson(`${apiBaseUrl}/api/graph/views?${query}`, signal, authToken);
}

export function saveGraphView(
  apiBaseUrl: string,
  authToken: string,
  payload: Pick<GraphViewRecord, 'graph_id' | 'view_id' | 'name' | 'state' | 'revision'>,
): Promise<GraphViewRecord & { saved: boolean }> {
  return postJson(`${apiBaseUrl}/api/graph/views`, authToken, payload);
}

export function deleteGraphView(
  apiBaseUrl: string,
  authToken: string,
  graphId: string,
  viewId: string,
): Promise<{ deleted: boolean; view_id: string }> {
  const query = new URLSearchParams({ graph_id: graphId });
  return deleteJson(
    `${apiBaseUrl}/api/graph/views/${encodeURIComponent(viewId)}?${query}`,
    authToken,
  );
}

export function loadNodeOccurrences(
  apiBaseUrl: string,
  authToken: string,
  notation: string,
  signal: AbortSignal,
): Promise<{ occurrences: NodeOccurrence[] }> {
  const query = new URLSearchParams({ notation });
  return loadJson(`${apiBaseUrl}/api/graph/node-occurrences?${query}`, signal, authToken);
}

function postJson<T>(url: string, authToken: string, payload: object): Promise<T> {
  return requestJson<T>(url, authToken, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

function deleteJson<T>(url: string, authToken: string): Promise<T> {
  return requestJson<T>(url, authToken, { method: 'DELETE' });
}

async function requestJson<T>(url: string, authToken: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Basic ${authToken}`);
  const response = await fetch(url, {
    ...init,
    headers,
  });
  if (response.status === 401) {
    throw new AuthError();
  }
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  if (response.status === 204 || response.headers.get('Content-Length') === '0') {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function responseErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: unknown };
    if (typeof payload.error === 'string' && payload.error) {
      return payload.error;
    }
  } catch {
    return `Graph API вернул HTTP ${response.status}`;
  }
  return `Graph API вернул HTTP ${response.status}`;
}
