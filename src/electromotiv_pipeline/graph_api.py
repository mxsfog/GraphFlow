from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from electromotiv_pipeline.orientdb import OrientDBClient

SUPPORTED_NOTATIONS = ("flow", "use_case", "component", "class")
DEFAULT_RUN_LIMIT = 6
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiNode:
    id: str
    label: str
    type: str
    shape: str
    position: dict[str, int]
    style: dict[str, object]
    data: dict[str, object]


@dataclass(frozen=True)
class ApiEdge:
    id: str
    source: str
    target: str
    type: str
    label: str
    style: dict[str, object]
    data: dict[str, object]


def run_graph_api(*, client: OrientDBClient, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), handler_for(client))
    LOGGER.warning("Graph API запущен: http://%s:%s", host, port)
    server.serve_forever()


def handler_for(client: OrientDBClient) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                payload = route_get(client, self.path)
            except ValueError as exc:
                self.write_json({"error": str(exc)}, status=400)
                return
            except RuntimeError as exc:
                self.write_json({"error": str(exc)}, status=500)
                return

            if payload is None:
                self.write_json({"error": "Маршрут не найден."}, status=404)
                return
            self.write_json(payload)

        def write_json(self, payload: dict[str, object], *, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def route_get(client: OrientDBClient, raw_path: str) -> dict[str, object] | None:
    parsed = urllib.parse.urlsplit(raw_path)
    query = urllib.parse.parse_qs(parsed.query)
    notation = first_query_value(query, "notation", "flow")
    run_id = first_query_value(query, "run_id", "")
    limit = int_or_default(
        first_query_value(query, "limit", str(DEFAULT_RUN_LIMIT)),
        DEFAULT_RUN_LIMIT,
    )
    if notation not in SUPPORTED_NOTATIONS:
        raise ValueError(f"Неподдерживаемая нотация: {notation}")

    if parsed.path == "/health":
        return {"status": "ok"}
    if parsed.path == "/api/graph/schema":
        return graph_api_schema()
    if parsed.path == "/api/search-runs":
        return {"runs": list_search_runs(client)}
    if parsed.path == "/api/graph/latest-run":
        return latest_run_graph_payload(client=client, notation=notation, limit=limit)
    if parsed.path.startswith("/api/graph/run/"):
        path_run_id = urllib.parse.unquote(parsed.path.removeprefix("/api/graph/run/"))
        return run_graph_payload(
            client=client,
            run_id=path_run_id or run_id,
            notation=notation,
            limit=limit,
        )
    return None


def list_search_runs(client: OrientDBClient) -> list[dict[str, object]]:
    rows = orient_rows(
        client,
        "SELECT run_id, query, model, finished_at, ranked_count FROM SearchRun "
        "ORDER BY finished_at DESC LIMIT 20",
    )
    return [
        {
            "run_id": row.get("run_id", ""),
            "query": row.get("query", ""),
            "model": row.get("model", ""),
            "finished_at": row.get("finished_at", ""),
            "ranked_count": row.get("ranked_count", 0),
        }
        for row in rows
    ]


def latest_run_graph_payload(
    *,
    client: OrientDBClient,
    notation: str,
    limit: int,
) -> dict[str, object]:
    rows = orient_rows(client, "SELECT FROM SearchRun ORDER BY finished_at DESC LIMIT 1")
    if not rows:
        return empty_graph(notation=notation, graph_id="latest-run")
    return search_run_graph_payload(client=client, run_row=rows[0], notation=notation, limit=limit)


def run_graph_payload(
    *,
    client: OrientDBClient,
    run_id: str,
    notation: str,
    limit: int,
) -> dict[str, object]:
    if not run_id:
        return latest_run_graph_payload(client=client, notation=notation, limit=limit)
    rows = orient_rows(
        client,
        f"SELECT FROM SearchRun WHERE run_id = '{sql_string(run_id)}' LIMIT 1",
    )
    if not rows:
        return empty_graph(notation=notation, graph_id=run_id)
    return search_run_graph_payload(client=client, run_row=rows[0], notation=notation, limit=limit)


def search_run_graph_payload(
    *,
    client: OrientDBClient,
    run_row: dict[str, object],
    notation: str,
    limit: int,
) -> dict[str, object]:
    run_id = str(run_row.get("run_id") or "")
    query = str(run_row.get("query") or "")
    model = str(run_row.get("model") or "")
    links = news_links_for_run(client, run_id=run_id, limit=max(1, min(limit, 12)))
    nodes = runtime_nodes(run_row=run_row, links=links, notation=notation)
    edges = runtime_edges(run_id=run_id, links=links, notation=notation)
    return {
        "graph_id": f"run:{run_id}",
        "title": f"Запуск: {short_text(query, 80)}",
        "notation": notation,
        "source": {
            "database": "news",
            "root_class": "SearchRun",
            "run_id": run_id,
            "model": model,
            "links_shown": len(links),
        },
        "nodes": [node_to_dict(node) for node in nodes],
        "edges": [edge_to_dict(edge) for edge in edges],
    }


def news_links_for_run(
    client: OrientDBClient,
    *,
    run_id: str,
    limit: int,
) -> list[dict[str, object]]:
    return orient_rows(
        client,
        f"SELECT FROM NewsLink WHERE run_id = '{sql_string(run_id)}' "
        f"ORDER BY llm_score DESC LIMIT {limit}",
    )


def runtime_nodes(
    *,
    run_row: dict[str, object],
    links: list[dict[str, object]],
    notation: str,
) -> list[ApiNode]:
    run_id = str(run_row.get("run_id") or "")
    query = str(run_row.get("query") or "")
    model = str(run_row.get("model") or "")
    topic_y = len(links) * 132 + 80
    nodes = [
        runtime_node(
            node_id="actor:user",
            label="Пользователь",
            node_type="actor",
            stored_shape="actor",
            x=-660,
            y=260,
            notation=notation,
            data={"role": "user"},
        ),
        runtime_node(
            node_id="run",
            label=f"Запуск поиска\n{short_text(query, 46)}",
            node_type="process",
            stored_shape="rounded_rectangle",
            x=-380,
            y=250,
            notation=notation,
            data={
                "class": "SearchRun",
                "run_id": run_id,
                "query": query,
                "model": model,
                "finished_at": run_row.get("finished_at", ""),
                "candidates_count": run_row.get("candidates_count", 0),
                "ranked_count": run_row.get("ranked_count", 0),
            },
        ),
        runtime_node(
            node_id="component:rss",
            label="Google News RSS",
            node_type="component",
            stored_shape="component",
            x=-70,
            y=20,
            notation=notation,
            data={"class": "GoogleNewsSource"},
        ),
        runtime_node(
            node_id="component:model",
            label=short_text(model or "LLM", 36),
            node_type="model",
            stored_shape="component",
            x=-70,
            y=500,
            notation=notation,
            data={"class": "ModelRun", "model": model},
        ),
        runtime_node(
            node_id="storage:orientdb",
            label="OrientDB",
            node_type="storage",
            stored_shape="database",
            x=-380,
            y=520,
            notation=notation,
            data={"class": "OrientDB", "database": "news"},
        ),
        runtime_node(
            node_id="storage:sheets",
            label="Google Sheets",
            node_type="storage",
            stored_shape="document",
            x=-380,
            y=660,
            notation=notation,
            data={"class": "GoogleSheetsExport"},
        ),
    ]
    nodes.extend(news_link_nodes(links=links, notation=notation))
    nodes.extend(source_nodes(links=links, notation=notation))
    nodes.append(
        runtime_node(
            node_id="topic:query",
            label=f"Тема\n{short_text(query, 42)}",
            node_type="topic",
            stored_shape="rounded_rectangle",
            x=530,
            y=topic_y,
            notation=notation,
            data={"class": "Topic", "name": query},
        )
    )
    return nodes


def news_link_nodes(*, links: list[dict[str, object]], notation: str) -> list[ApiNode]:
    nodes: list[ApiNode] = []
    for index, link in enumerate(links):
        y = index * 118
        score = float_or_default(link.get("llm_score"), 0.0)
        nodes.append(
            runtime_node(
                node_id=news_node_id(link),
                label=f"{index + 1}. {short_text(str(link.get('title') or ''), 62)}",
                node_type="news",
                stored_shape="document",
                x=330,
                y=y,
                notation=notation,
                data={
                    "class": "NewsLink",
                    "title": link.get("title", ""),
                    "url": link.get("url", ""),
                    "source": link.get("source", ""),
                    "domain": link.get("domain", ""),
                    "llm_score": score,
                    "keywords": link.get("keywords", ""),
                    "reason": link.get("reason", ""),
                    "published_at": link.get("published_at", ""),
                },
            )
        )
    return nodes


def source_nodes(*, links: list[dict[str, object]], notation: str) -> list[ApiNode]:
    seen: dict[str, dict[str, object]] = {}
    for link in links:
        key = source_key(link)
        if key not in seen:
            seen[key] = link

    nodes: list[ApiNode] = []
    for index, link in enumerate(seen.values()):
        nodes.append(
            runtime_node(
                node_id=source_node_id(link),
                label=short_text(source_name(link), 34),
                node_type="source",
                stored_shape="rounded_rectangle",
                x=820,
                y=index * 132,
                notation=notation,
                data={
                    "class": "Source",
                    "name": source_name(link),
                    "domain": link.get("domain", ""),
                },
            )
        )
    return nodes


def runtime_edges(
    *,
    run_id: str,
    links: list[dict[str, object]],
    notation: str,
) -> list[ApiEdge]:
    edges = [
        runtime_edge("e_user_run", "actor:user", "run", "request", "запрос", notation),
        runtime_edge("e_run_rss", "run", "component:rss", "request", "RSS запрос", notation),
        runtime_edge(
            "e_run_model",
            "run",
            "component:model",
            "analyzed_by",
            "LLM оценка",
            notation,
        ),
        runtime_edge(
            "e_run_orientdb",
            "run",
            "storage:orientdb",
            "saved_to",
            "сохранено",
            notation,
        ),
        runtime_edge("e_run_sheets", "run", "storage:sheets", "exported_to", "экспорт", notation),
        runtime_edge("e_run_topic", "run", "topic:query", "about", "тема", notation),
    ]
    for index, link in enumerate(links):
        news_id = news_node_id(link)
        edges.extend(
            [
                runtime_edge(f"e_found_{index}", "run", news_id, "found", "найдено", notation),
                runtime_edge(
                    f"e_source_{index}",
                    news_id,
                    source_node_id(link),
                    "from_source",
                    "источник",
                    notation,
                ),
                runtime_edge(
                    f"e_model_{index}",
                    "component:model",
                    news_id,
                    "score",
                    f"score {float_or_default(link.get('llm_score'), 0.0):.2f}",
                    notation,
                ),
            ]
        )
    return edges


def notation_shape(*, node_type: str, stored_shape: str, notation: str) -> str:
    if notation == "use_case":
        return "actor" if node_type == "actor" else "ellipse"
    if notation == "component":
        return "component"
    if notation == "class":
        return "class"
    if notation == "flow":
        if node_type == "condition":
            return "diamond"
        if node_type in {"data", "news"}:
            return "document"
        if node_type == "storage":
            return "database" if stored_shape == "database" else "document"
        if node_type == "model":
            return "component"
        return stored_shape or "rounded_rectangle"
    return stored_shape or "rounded_rectangle"


def merge_style(
    *,
    stored_style: dict[str, object],
    shape: str,
    node_type: str,
    notation: str,
) -> dict[str, object]:
    palette = {
        "actor": {"background": "#f8fafc", "borderColor": "#0f172a"},
        "process": {"background": "#e8f2ff", "borderColor": "#2563eb"},
        "condition": {"background": "#fff7ed", "borderColor": "#ea580c"},
        "data": {"background": "#f8fafc", "borderColor": "#64748b"},
        "news": {"background": "#f8fafc", "borderColor": "#0f766e"},
        "source": {"background": "#fff7ed", "borderColor": "#ea580c"},
        "topic": {"background": "#ecfdf5", "borderColor": "#059669"},
        "model": {"background": "#f5f3ff", "borderColor": "#7c3aed"},
        "storage": {"background": "#f1f5f9", "borderColor": "#475569"},
        "component": {"background": "#f5f3ff", "borderColor": "#7c3aed"},
        "class": {"background": "#ecfdf5", "borderColor": "#059669"},
    }
    base = {
        "shape": shape,
        "notation": notation,
        "borderWidth": 2,
        **palette.get(node_type, {"background": "#ffffff", "borderColor": "#334155"}),
    }
    return {**base, **stored_style}


def merge_edge_style(
    *,
    stored_style: dict[str, object],
    edge_type: str,
    notation: str,
) -> dict[str, object]:
    if notation == "use_case" or edge_type == "include":
        base: dict[str, object] = {
            "stroke": "#334155",
            "strokeWidth": 1.6,
            "strokeDasharray": "6 4",
        }
    elif edge_type == "decision":
        base = {"stroke": "#ea580c", "strokeWidth": 2}
    elif edge_type in {"found", "request", "candidate"}:
        base = {"stroke": "#2563eb", "strokeWidth": 2.2}
    elif edge_type in {"from_source", "source"}:
        base = {"stroke": "#ea580c", "strokeWidth": 1.9}
    elif edge_type in {"about", "score"}:
        base = {"stroke": "#059669", "strokeWidth": 1.9}
    elif edge_type in {"analyzed_by"}:
        base = {"stroke": "#7c3aed", "strokeWidth": 2.1}
    elif edge_type in {"saved_to", "exported_to"}:
        base = {"stroke": "#475569", "strokeWidth": 2.0}
    else:
        base = {"stroke": "#475569", "strokeWidth": 1.8}
    return {**base, **stored_style}


def runtime_node(
    *,
    node_id: str,
    label: str,
    node_type: str,
    stored_shape: str,
    x: int,
    y: int,
    notation: str,
    data: dict[str, object],
) -> ApiNode:
    shape = notation_shape(node_type=node_type, stored_shape=stored_shape, notation=notation)
    return ApiNode(
        id=node_id,
        label=label,
        type=node_type,
        shape=shape,
        position={"x": x, "y": y},
        style=merge_style(stored_style={}, shape=shape, node_type=node_type, notation=notation),
        data=data,
    )


def runtime_edge(
    edge_id: str,
    source: str,
    target: str,
    edge_type: str,
    label: str,
    notation: str,
) -> ApiEdge:
    return ApiEdge(
        id=edge_id,
        source=source,
        target=target,
        type=edge_type,
        label="include" if notation == "use_case" else label,
        style=merge_edge_style(stored_style={}, edge_type=edge_type, notation=notation),
        data={},
    )


def news_node_id(link: dict[str, object]) -> str:
    value = str(link.get("url") or link.get("@rid") or link.get("title") or "")
    return "news:" + stable_hash(value)


def source_node_id(link: dict[str, object]) -> str:
    return "source:" + stable_hash(source_key(link))


def source_key(link: dict[str, object]) -> str:
    name = source_name(link)
    domain = str(link.get("domain") or "")
    return f"{name}|{domain}"


def source_name(link: dict[str, object]) -> str:
    return str(link.get("source") or link.get("source_name") or link.get("domain") or "unknown")


def stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def short_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def graph_api_schema() -> dict[str, object]:
    return {
        "endpoints": [
            "/api/search-runs",
            "/api/graph/latest-run?notation=flow&limit=6",
            "/api/graph/run/{run_id}?notation=flow&limit=6",
        ],
        "notations": list(SUPPORTED_NOTATIONS),
        "storage": {
            "primary": ["SearchRun", "NewsLink", "Source", "Topic", "ModelRun"],
        },
        "node": {
            "id": "stable runtime node id",
            "label": "human-readable label",
            "type": "semantic node type",
            "shape": "notation-derived shape",
            "position": {"x": "layout x", "y": "layout y"},
            "style": "notation-derived style",
            "data": "fields from OrientDB runtime entities",
        },
        "edge": {
            "id": "stable runtime edge id",
            "source": "source node id",
            "target": "target node id",
            "type": "semantic edge type",
            "label": "edge label or include for use_case",
            "style": "notation-derived style",
        },
    }


def empty_graph(*, notation: str, graph_id: str) -> dict[str, object]:
    return {"graph_id": graph_id, "notation": notation, "nodes": [], "edges": []}


def orient_rows(client: OrientDBClient, sql: str) -> list[dict[str, object]]:
    response = client.command(sql)
    result = response.get("result", [])
    return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []


def node_to_dict(node: ApiNode) -> dict[str, object]:
    return {
        "id": node.id,
        "label": node.label,
        "type": node.type,
        "shape": node.shape,
        "position": node.position,
        "style": node.style,
        "data": node.data,
    }


def edge_to_dict(edge: ApiEdge) -> dict[str, object]:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "type": edge.type,
        "label": edge.label,
        "style": edge.style,
        "data": edge.data,
    }


def first_query_value(query: dict[str, list[str]], key: str, default: str) -> str:
    values = query.get(key)
    return values[0] if values else default


def int_or_default(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def float_or_default(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
