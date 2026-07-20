export type ExportNode = {
  id: string;
  label: string;
  nodeType: string;
  shape: string;
  position: { x: number; y: number };
  width?: number;
  height?: number;
  fill?: string;
  stroke?: string;
  metric?: string;
  sharedMapCount?: number;
};

export type ExportEdge = {
  source: string;
  target: string;
  label: string;
  edgeType: string;
  stroke?: string;
  dashed?: boolean;
};

export type GraphExport = {
  title: string;
  nodes: ExportNode[];
  edges: ExportEdge[];
};

const NODE_WIDTH = 220;
const NODE_HEIGHT = 100;
const PADDING = 80;

export function graphSvg(graph: GraphExport): string {
  const bounds = graphBounds(graph.nodes);
  const offsetX = PADDING - bounds.left;
  const offsetY = PADDING + 52 - bounds.top;
  const width = Math.max(960, bounds.width + PADDING * 2);
  const height = Math.max(540, bounds.height + PADDING * 2 + 52);
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const markerId = `arrow-${stableKey(graph.title)}`;
  const edgeMarkup = graph.edges.flatMap((edge) => {
    const source = nodesById.get(edge.source);
    const target = nodesById.get(edge.target);
    if (!source || !target) {
      return [];
    }
    const from = nodeCenter(source, offsetX, offsetY);
    const to = nodeCenter(target, offsetX, offsetY);
    const middleX = Math.round((from.x + to.x) / 2);
    const path = `M ${from.x} ${from.y} L ${middleX} ${from.y} L ${middleX} ${to.y} L ${to.x} ${to.y}`;
    const labelX = middleX + 6;
    const labelY = Math.round((from.y + to.y) / 2) - 6;
    return [
      `<path d="${path}" fill="none" stroke="${escapeXml(edge.stroke || '#64748b')}" stroke-width="2"${edge.dashed ? ' stroke-dasharray="7 5"' : ''} marker-end="url(#${markerId})"/>`,
      edge.label
        ? `<text x="${labelX}" y="${labelY}" class="edge-label">${escapeXml(edge.label)}</text>`
        : '',
    ];
  }).join('');
  const nodeMarkup = graph.nodes.map((node) => renderNode(node, offsetX, offsetY)).join('');
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <defs>
    <marker id="${markerId}" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#64748b"/></marker>
    <style>text{font-family:Arial,sans-serif;fill:#172033;letter-spacing:0}.title{font-size:26px;font-weight:700}.node-label{font-size:14px;font-weight:700}.node-meta{font-size:11px;fill:#5b6472}.edge-label{font-size:11px;fill:#3f4857;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round}</style>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc"/>
  <text x="${PADDING}" y="42" class="title">${escapeXml(graph.title)}</text>
  ${edgeMarkup}
  ${nodeMarkup}
</svg>`;
}

export function downloadGraphSvg(graph: GraphExport): void {
  downloadBlob(`${safeFilename(graph.title)}.svg`, new Blob([graphSvg(graph)], {
    type: 'image/svg+xml;charset=utf-8',
  }));
}

export function downloadGraphPresentation(graph: GraphExport): void {
  const svg = graphSvg(graph).replace(/^<\?xml[^>]*>\s*/, '');
  const title = escapeHtml(graph.title);
  const generatedAt = new Date().toLocaleString('ru-RU');
  const html = `<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>${title}</title>
<style>*{box-sizing:border-box}body{margin:0;background:#111827;color:#111827;font-family:Arial,sans-serif}.slide{display:none;width:100vw;height:100vh;background:#f8fafc;padding:5vh 6vw}.slide.active{display:flex}.cover{align-items:center;justify-content:center;flex-direction:column;text-align:center}.cover h1{font-size:7vw;margin:0 0 2vh}.cover p{font-size:2vw;color:#475569}.graph{align-items:center;justify-content:center}.graph svg{width:100%;height:100%}.summary{flex-direction:column}.summary h2{font-size:4vw}.summary dl{display:grid;grid-template-columns:max-content 1fr;gap:2vh 3vw;font-size:2vw}.summary dt{font-weight:700}.nav{position:fixed;right:2vw;bottom:2vh;color:#fff;font-size:14px}</style></head>
<body><section class="slide cover active"><h1>${title}</h1><p>Интерактивная карта GraphFlow</p></section>
<section class="slide graph">${svg}</section>
<section class="slide summary"><h2>Состав представления</h2><dl><dt>Узлы</dt><dd>${graph.nodes.length}</dd><dt>Связи</dt><dd>${graph.edges.length}</dd><dt>Сформировано</dt><dd>${escapeHtml(generatedAt)}</dd></dl></section>
<div class="nav">← → или пробел</div><script>const s=[...document.querySelectorAll('.slide')];let i=0;function show(n){s[i].classList.remove('active');i=(n+s.length)%s.length;s[i].classList.add('active')}addEventListener('keydown',e=>{if(['ArrowRight',' ','PageDown'].includes(e.key))show(i+1);if(['ArrowLeft','PageUp'].includes(e.key))show(i-1)});</script></body></html>`;
  downloadBlob(`${safeFilename(graph.title)}-presentation.html`, new Blob([html], {
    type: 'text/html;charset=utf-8',
  }));
}

function renderNode(node: ExportNode, offsetX: number, offsetY: number): string {
  const width = node.width || NODE_WIDTH;
  const height = node.height || NODE_HEIGHT;
  const x = Math.round(node.position.x + offsetX);
  const y = Math.round(node.position.y + offsetY);
  const fill = escapeXml(node.fill || '#ffffff');
  const stroke = escapeXml(node.sharedMapCount && node.sharedMapCount > 1 ? '#db2777' : node.stroke || '#334155');
  const strokeWidth = node.sharedMapCount && node.sharedMapCount > 1 ? 4 : 2;
  const shape = nodeShape(node.shape, x, y, width, height, fill, stroke, strokeWidth);
  const lines = wrapLabel(node.label, 30).slice(0, 4);
  const startY = y + height / 2 - ((lines.length - 1) * 17) / 2;
  const label = lines.map((line, index) =>
    `<text x="${x + width / 2}" y="${startY + index * 17}" text-anchor="middle" class="node-label">${escapeXml(line)}</text>`,
  ).join('');
  const metric = node.metric
    ? `<text x="${x + width / 2}" y="${y + height - 10}" text-anchor="middle" class="node-meta">${escapeXml(node.metric)}</text>`
    : '';
  const shared = node.sharedMapCount && node.sharedMapCount > 1
    ? `<text x="${x + width - 8}" y="${y + 14}" text-anchor="end" class="node-meta">${node.sharedMapCount} карт</text>`
    : '';
  return `<g>${shape}${label}${metric}${shared}</g>`;
}

function nodeShape(
  shape: string,
  x: number,
  y: number,
  width: number,
  height: number,
  fill: string,
  stroke: string,
  strokeWidth: number,
): string {
  if (shape === 'ellipse' || shape === 'circle' || shape === 'actor') {
    return `<ellipse cx="${x + width / 2}" cy="${y + height / 2}" rx="${width / 2}" ry="${height / 2}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
  }
  if (shape === 'diamond') {
    return `<polygon points="${x + width / 2},${y} ${x + width},${y + height / 2} ${x + width / 2},${y + height} ${x},${y + height / 2}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
  }
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${shape === 'database' ? 28 : 6}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function graphBounds(nodes: ExportNode[]) {
  if (nodes.length === 0) {
    return { left: 0, top: 0, width: 800, height: 380 };
  }
  const left = Math.min(...nodes.map((node) => node.position.x));
  const top = Math.min(...nodes.map((node) => node.position.y));
  const right = Math.max(...nodes.map((node) => node.position.x + (node.width || NODE_WIDTH)));
  const bottom = Math.max(...nodes.map((node) => node.position.y + (node.height || NODE_HEIGHT)));
  return { left, top, width: right - left, height: bottom - top };
}

function nodeCenter(node: ExportNode, offsetX: number, offsetY: number) {
  return {
    x: Math.round(node.position.x + offsetX + (node.width || NODE_WIDTH) / 2),
    y: Math.round(node.position.y + offsetY + (node.height || NODE_HEIGHT) / 2),
  };
}

function wrapLabel(value: string, limit: number): string[] {
  const words = value.replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  const lines: string[] = [];
  for (const word of words) {
    const current = lines.at(-1) || '';
    if (!current || `${current} ${word}`.length > limit) {
      lines.push(word);
    } else {
      lines[lines.length - 1] = `${current} ${word}`;
    }
  }
  return lines.length > 0 ? lines : ['Без названия'];
}

function safeFilename(value: string): string {
  const normalized = value.replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, ' ').trim();
  return (normalized || 'graph').slice(0, 100);
}

function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function escapeXml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&apos;',
  })[character] || character);
}

function escapeHtml(value: string): string {
  return escapeXml(value);
}

function stableKey(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}
