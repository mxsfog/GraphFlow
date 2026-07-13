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

function postJson<T>(url: string, authToken: string, payload: object): Promise<T> {
  return requestJson<T>(url, authToken, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
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
