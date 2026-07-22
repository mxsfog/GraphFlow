from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import threading
import unicodedata
import urllib.parse
from dataclasses import dataclass, replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from electromotiv_pipeline.config import DEFAULT_SCHEMA_PATH
from electromotiv_pipeline.orientdb import OrientDBClient, now_orient, parse_datetime

SUPPORTED_NOTATIONS = ("flow", "use_case", "component", "class")
SUPPORTED_SHAPES = {
    "rounded_rectangle",
    "document",
    "diamond",
    "ellipse",
    "circle",
    "actor",
    "component",
    "class",
    "database",
}
NODE_SHAPES_BY_NOTATION = {
    "use_case": {
        "actor": "actor",
        "source": "actor",
        "process": "ellipse",
        "news": "ellipse",
        "topic": "ellipse",
        "storage": "database",
    },
    "component": {
        "component": "component",
        "model": "component",
        "process": "component",
        "storage": "database",
        "news": "document",
        "data": "document",
    },
    "class": {
        "actor": "actor",
        "storage": "database",
        "component": "component",
    },
    "flow": {
        "condition": "diamond",
        "data": "document",
        "news": "document",
        "model": "component",
    },
}
DEFAULT_SHAPE_BY_NOTATION = {
    "use_case": "component",
    "component": "rounded_rectangle",
    "class": "class",
    "flow": "rounded_rectangle",
}
DEFAULT_EDGE_STYLE = {"stroke": "#475569", "strokeWidth": 1.8}
USE_CASE_EDGE_STYLE = {
    "stroke": "#334155",
    "strokeWidth": 1.6,
    "strokeDasharray": "6 4",
}
EDGE_STYLES = {
    "todo": {"stroke": "#dc2626", "strokeWidth": 2.2, "strokeDasharray": "8 5"},
    "follow": {"stroke": "#2563eb", "strokeWidth": 2.4},
    "properties": {"stroke": "#0f766e", "strokeWidth": 2.0, "strokeDasharray": "3 4"},
    "decision": {"stroke": "#ea580c", "strokeWidth": 2},
    "found": {"stroke": "#2563eb", "strokeWidth": 2.2},
    "request": {"stroke": "#2563eb", "strokeWidth": 2.2},
    "candidate": {"stroke": "#2563eb", "strokeWidth": 2.2},
    "from_source": {"stroke": "#ea580c", "strokeWidth": 1.9},
    "source": {"stroke": "#ea580c", "strokeWidth": 1.9},
    "about": {"stroke": "#059669", "strokeWidth": 1.9},
    "score": {"stroke": "#059669", "strokeWidth": 1.9},
    "analyzed_by": {"stroke": "#7c3aed", "strokeWidth": 2.1},
    "saved_to": {"stroke": "#475569", "strokeWidth": 2.0},
    "exported_to": {"stroke": "#475569", "strokeWidth": 2.0},
}
NODE_STYLE_PALETTE = {
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
DEFAULT_NODE_STYLE = {"background": "#ffffff", "borderColor": "#334155"}
DEFAULT_RUN_LIMIT = 6
MAX_REQUEST_BYTES = 2_000_000
MAX_GRAPH_GROUPS = 100
MAX_GROUP_NODES = 200
MAX_GROUP_CHILDREN = 50
MAX_GRAPH_TEMPLATES = 50
MAX_GRAPH_VIEWS = 50
MAX_OCCURRENCE_ROWS = 10_000
MAX_VIEW_STATE_BYTES = 100_000
LOGGER = logging.getLogger(__name__)
ANNOTATION_LOCK = threading.RLock()
WORKSPACE_LOCK = threading.RLock()


class ConflictError(RuntimeError):
    """Конфликт версий при сохранении графа."""


@dataclass(frozen=True)
class ApiAuth:
    username: str
    password: str


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


@dataclass(frozen=True)
class GraphAnnotationRecord:
    payload: dict[str, object]
    revision: int


def run_graph_api(*, client: OrientDBClient, host: str, port: int, auth: ApiAuth) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Graph API без TLS разрешено запускать только на loopback-адресе.")
    client.ensure_schema(DEFAULT_SCHEMA_PATH)
    server = ThreadingHTTPServer((host, port), handler_for(client, auth=auth))
    LOGGER.warning("Graph API запущен: http://%s:%s", host, port)
    server.serve_forever()


class GraphRequestHandler(BaseHTTPRequestHandler):
    client: OrientDBClient
    auth: ApiAuth

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.write_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path != "/health" and not self.require_authorization():
            return
        try:
            self.write_route_response(route_get(self.client, self.path))
        except (ValueError, RuntimeError) as exc:
            self.write_api_error(exc)

    def do_POST(self) -> None:
        if not self.require_authorization():
            return
        try:
            response = route_post(self.client, self.path, self.read_json_body())
            self.write_route_response(response)
        except (ValueError, ConflictError, RuntimeError) as exc:
            self.write_api_error(exc)

    def do_DELETE(self) -> None:
        if not self.require_authorization():
            return
        try:
            self.write_route_response(route_delete(self.client, self.path))
        except (ValueError, ConflictError, RuntimeError) as exc:
            self.write_api_error(exc)

    def require_authorization(self) -> bool:
        if is_authorized(self.headers.get("Authorization"), self.auth):
            return True
        self.write_json({"error": "Требуется авторизация."}, status=401, auth_required=True)
        return False

    def write_route_response(self, payload: dict[str, object] | None) -> None:
        if payload is None:
            self.write_json({"error": "Маршрут не найден."}, status=404)
            return
        self.write_json(payload)

    def write_api_error(self, error: Exception) -> None:
        status = (
            409
            if isinstance(error, ConflictError)
            else 400
            if isinstance(error, ValueError)
            else 503
        )
        self.write_json({"error": str(error)}, status=status)

    def read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Размер JSON-запроса превышает допустимый лимит.")
        raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ValueError("Тело запроса должно быть валидным JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Тело запроса должно быть JSON-объектом.")
        return payload

    def write_json(
        self,
        payload: dict[str, object],
        *,
        status: int = 200,
        auth_required: bool = False,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.write_common_headers()
        if auth_required:
            self.send_header("WWW-Authenticate", 'Basic realm="ElectroMotiv Graph API"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_common_headers(self) -> None:
        origin = allowed_origin(self.headers.get("Origin"))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")

    def log_message(self, _format: str, *args: object) -> None:
        return


def handler_for(client: OrientDBClient, *, auth: ApiAuth) -> type[BaseHTTPRequestHandler]:
    Handler = type("ConfiguredGraphRequestHandler", (GraphRequestHandler,), {})
    Handler.client = client
    Handler.auth = auth
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
        client.command("SELECT 1")
        return {"status": "ok", "database": client.database}
    if parsed.path == "/api/session":
        return {"authenticated": True}
    if parsed.path == "/api/graph/schema":
        return graph_api_schema()
    if parsed.path == "/api/search-runs":
        return {"runs": list_search_runs(client)}
    if parsed.path == "/api/graph/node-occurrences":
        return {"occurrences": list_node_occurrences(client, notation=notation)}
    if parsed.path == "/api/graph/groups":
        graph_id = first_query_value(query, "graph_id", "")
        return {"groups": list_graph_groups(client, graph_id=graph_id, notation=notation)}
    if parsed.path == "/api/graph/views":
        graph_id = first_query_value(query, "graph_id", "")
        return {"views": list_graph_views(client, graph_id=graph_id)}
    if parsed.path == "/api/graph/templates":
        return {"templates": list_graph_templates(client)}
    if parsed.path.startswith("/api/graph/templates/"):
        template_id = urllib.parse.unquote(parsed.path.removeprefix("/api/graph/templates/"))
        return get_graph_template(client, template_id=template_id)
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
    if parsed.path.startswith("/api/graph/custom/"):
        graph_id = urllib.parse.unquote(parsed.path.removeprefix("/api/graph/custom/"))
        return custom_graph_payload(client=client, graph_id=graph_id, notation=notation)
    return None


def route_post(
    client: OrientDBClient,
    raw_path: str,
    payload: dict[str, object],
) -> dict[str, object] | None:
    parsed = urllib.parse.urlsplit(raw_path)
    if parsed.path == "/api/graph/annotations":
        return save_graph_annotation(client, payload)
    if parsed.path == "/api/graph/annotations/batch":
        return save_graph_annotations_batch(client, payload)
    if parsed.path == "/api/graphs":
        return save_custom_graph(client, payload)
    if parsed.path == "/api/graph/groups":
        return save_graph_group(client, payload)
    if parsed.path == "/api/graph/views":
        return save_graph_view(client, payload)
    if parsed.path == "/api/graph/templates":
        return save_graph_template(client, payload)
    return None


def route_delete(client: OrientDBClient, raw_path: str) -> dict[str, object] | None:
    parsed = urllib.parse.urlsplit(raw_path)
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.path.startswith("/api/graph/groups/"):
        group_id = urllib.parse.unquote(parsed.path.removeprefix("/api/graph/groups/"))
        return delete_graph_group(
            client,
            graph_id=first_query_value(query, "graph_id", ""),
            notation=first_query_value(query, "notation", "flow"),
            group_id=group_id,
        )
    if parsed.path.startswith("/api/graph/templates/"):
        template_id = urllib.parse.unquote(parsed.path.removeprefix("/api/graph/templates/"))
        return delete_graph_template(client, template_id=template_id)
    if parsed.path.startswith("/api/graph/views/"):
        view_id = urllib.parse.unquote(parsed.path.removeprefix("/api/graph/views/"))
        return delete_graph_view(
            client,
            graph_id=first_query_value(query, "graph_id", ""),
            view_id=view_id,
        )
    return None


def is_authorized(header: str | None, auth: ApiAuth) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.removeprefix("Basic "), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return hmac.compare_digest(username, auth.username) and hmac.compare_digest(
        password,
        auth.password,
    )


def list_search_runs(client: OrientDBClient) -> list[dict[str, object]]:
    rows = orient_rows(
        client,
        "SELECT run_id, query, model, finished_at, ranked_count FROM SearchRun "
        "ORDER BY finished_at DESC LIMIT 20",
    )
    runs = [
        {
            "run_id": row.get("run_id", ""),
            "query": row.get("query", ""),
            "model": row.get("model", ""),
            "finished_at": row.get("finished_at", ""),
            "ranked_count": row.get("ranked_count", 0),
        }
        for row in rows
    ]
    try:
        graphs = orient_rows(
            client,
            "SELECT graph_id, title, source_type, updated_at FROM GraphDocument "
            "ORDER BY updated_at DESC LIMIT 20",
        )
    except RuntimeError as exc:
        if "Class not found: GraphDocument" in str(exc):
            return runs
        raise
    runs.extend(
        {
            "run_id": f"graph:{row.get('graph_id', '')}",
            "query": row.get("title", "Пользовательский граф"),
            "model": row.get("source_type", "custom"),
            "finished_at": row.get("updated_at", ""),
            "ranked_count": 0,
        }
        for row in graphs
        if row.get("graph_id")
    )
    return runs


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
    if run_id.startswith("graph:"):
        return custom_graph_payload(
            client=client,
            graph_id=run_id.removeprefix("graph:"),
            notation=notation,
        )
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
    graph_id = f"run:{run_id}"
    nodes = runtime_nodes(run_row=run_row, links=links, notation=notation)
    edges = runtime_edges(run_row=run_row, links=links, notation=notation)
    annotations = annotations_for_graph(client, graph_id=graph_id, notation=notation)
    nodes = [
        apply_node_annotation(node, annotations.get(("node", node.id)), notation) for node in nodes
    ]
    edges = [
        apply_edge_annotation(edge, annotations.get(("edge", edge.id)), notation) for edge in edges
    ]
    return {
        "graph_id": graph_id,
        "title": f"Запуск: {short_text(query, 80)}",
        "notation": notation,
        "source": {
            "database": client.database,
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
    rows = orient_rows(
        client,
        f"SELECT expand(out('Found')) FROM SearchRun WHERE run_id = '{sql_string(run_id)}' LIMIT 1",
    )
    results = [row for row in rows if str(row.get("@class") or "") in {"SearchResult", "NewsLink"}]
    results.sort(key=lambda row: float_or_default(row.get("llm_score"), 0.0), reverse=True)
    return results[:limit]


def runtime_nodes(
    *,
    run_row: dict[str, object],
    links: list[dict[str, object]],
    notation: str,
) -> list[ApiNode]:
    run_id = str(run_row.get("run_id") or "")
    query = str(run_row.get("query") or "")
    model = str(run_row.get("model") or "")
    link_spacing = 170
    center_y = max(0, (len(links) - 1) * link_spacing // 2)
    topic_y = max(760, len(links) * link_spacing + 80)
    nodes = [
        runtime_node(
            node_id="actor:user",
            label="Пользователь",
            node_type="actor",
            stored_shape="actor",
            x=-980,
            y=center_y,
            notation=notation,
            data={"role": "user"},
        ),
        runtime_node(
            node_id="run",
            label=f"Запуск поиска\n{short_text(query, 46)}",
            node_type="process",
            stored_shape="rounded_rectangle",
            x=-650,
            y=center_y,
            notation=notation,
            data={
                "class": "SearchRun",
                "run_id": run_id,
                "query": query,
                "model": model,
                "created_at": run_row.get("started_at") or run_row.get("finished_at", ""),
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
            x=-260,
            y=max(0, center_y - 260),
            notation=notation,
            data={"class": "GoogleNewsSource"},
        ),
        runtime_node(
            node_id="component:model",
            label=short_text(model or "LLM", 36),
            node_type="model",
            stored_shape="component",
            x=-260,
            y=center_y,
            notation=notation,
            data={"class": "ModelRun", "model": model},
        ),
        runtime_node(
            node_id="storage:orientdb",
            label="OrientDB",
            node_type="storage",
            stored_shape="database",
            x=-260,
            y=center_y + 260,
            notation=notation,
            data={"class": "OrientDB", "database": "news"},
        ),
    ]
    if int_or_default(run_row.get("sheets_saved_count"), 0) > 0:
        nodes.append(
            runtime_node(
                node_id="storage:sheets",
                label="Google Sheets",
                node_type="storage",
                stored_shape="document",
                x=-260,
                y=center_y + 430,
                notation=notation,
                data={
                    "class": "GoogleSheetsExport",
                    "saved_count": run_row.get("sheets_saved_count", 0),
                },
            )
        )
    nodes.extend(news_link_nodes(links=links, notation=notation))
    nodes.extend(source_nodes(links=links, notation=notation))
    nodes.append(
        runtime_node(
            node_id="topic:query",
            label=f"Тема\n{short_text(query, 42)}",
            node_type="topic",
            stored_shape="rounded_rectangle",
            x=-260,
            y=topic_y,
            notation=notation,
            data={"class": "Topic", "name": query},
        )
    )
    return nodes


def news_link_nodes(*, links: list[dict[str, object]], notation: str) -> list[ApiNode]:
    nodes: list[ApiNode] = []
    for index, link in enumerate(links):
        y = index * 170
        score = float_or_default(link.get("llm_score"), 0.0)
        nodes.append(
            runtime_node(
                node_id=news_node_id(link),
                label=f"{index + 1}. {short_text(str(link.get('title') or ''), 62)}",
                node_type="news",
                stored_shape="document",
                x=220,
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
                    "created_at": link.get("created_at") or link.get("published_at", ""),
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
                x=690,
                y=index * 170,
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
    run_row: dict[str, object],
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
        runtime_edge("e_run_topic", "run", "topic:query", "about", "тема", notation),
    ]
    if int_or_default(run_row.get("sheets_saved_count"), 0) > 0:
        edges.append(
            runtime_edge(
                "e_run_sheets",
                "run",
                "storage:sheets",
                "exported_to",
                "экспорт",
                notation,
            )
        )
    for link in links:
        news_id = news_node_id(link)
        stable_id = stable_hash(news_id)
        edges.extend(
            [
                runtime_edge(
                    f"e_found_{stable_id}",
                    "component:rss",
                    news_id,
                    "found",
                    "найдено",
                    notation,
                ),
                runtime_edge(
                    f"e_source_{stable_id}",
                    news_id,
                    source_node_id(link),
                    "from_source",
                    "источник",
                    notation,
                ),
                runtime_edge(
                    f"e_model_{stable_id}",
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
    if notation == "flow" and node_type == "storage":
        return "database" if stored_shape == "database" else "document"
    shape = NODE_SHAPES_BY_NOTATION.get(notation, {}).get(node_type)
    if notation == "class":
        return shape or "class"
    return shape or stored_shape or DEFAULT_SHAPE_BY_NOTATION.get(notation, "rounded_rectangle")


def merge_style(
    *,
    stored_style: dict[str, object],
    shape: str,
    node_type: str,
    notation: str,
) -> dict[str, object]:
    base = {
        "shape": shape,
        "notation": notation,
        "borderWidth": 2,
        **NODE_STYLE_PALETTE.get(node_type, DEFAULT_NODE_STYLE),
    }
    return {**base, **stored_style}


def merge_edge_style(
    *,
    stored_style: dict[str, object],
    edge_type: str,
    notation: str,
) -> dict[str, object]:
    if notation == "use_case" or edge_type == "include":
        base = USE_CASE_EDGE_STYLE
    else:
        base = EDGE_STYLES.get(edge_type, DEFAULT_EDGE_STYLE)
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
        label="include" if edge_type == "include" else label,
        style=merge_edge_style(stored_style={}, edge_type=edge_type, notation=notation),
        data={},
    )


def save_graph_annotation(
    client: OrientDBClient,
    request_payload: dict[str, object],
) -> dict[str, object]:
    graph_id = required_string(request_payload, "graph_id")
    element_id = required_string(request_payload, "element_id")
    element_kind = required_string(request_payload, "element_kind")
    notation = required_string(request_payload, "notation")
    revision = int_or_default(request_payload.get("revision"), -1)
    validate_identifier(graph_id, "graph_id")
    validate_identifier(element_id, "element_id")
    if element_kind not in {"node", "edge"}:
        raise ValueError("element_kind должен быть node или edge.")
    if notation not in SUPPORTED_NOTATIONS:
        raise ValueError(f"Неподдерживаемая нотация: {notation}")
    if revision < 0:
        raise ValueError("revision должен быть неотрицательным целым числом.")
    annotation_payload = request_payload.get("payload")
    if not isinstance(annotation_payload, dict):
        raise ValueError("payload должен быть JSON-объектом.")
    validate_annotation_payload(element_kind, annotation_payload)
    if not graph_element_exists(
        client,
        graph_id=graph_id,
        element_kind=element_kind,
        element_id=element_id,
        notation=notation,
    ):
        raise ValueError("Указанный элемент графа не существует.")

    with ANNOTATION_LOCK:
        existing = orient_rows(
            client,
            "SELECT FROM GraphAnnotation "
            f"WHERE graph_id = '{sql_string(graph_id)}' "
            f"AND notation = '{sql_string(notation)}' "
            f"AND element_id = '{sql_string(element_id)}' "
            f"AND element_kind = '{sql_string(element_kind)}' LIMIT 1",
        )
        current_revision = int_or_default(existing[0].get("revision"), 0) if existing else 0
        if revision != current_revision:
            raise ConflictError(
                f"Конфликт версии элемента {element_id}: "
                f"ожидалась {revision}, текущая {current_revision}."
            )
        next_revision = current_revision + 1
        current_payload = json_object(existing[0].get("payload_json")) if existing else {}
        merged_annotation_payload = {**current_payload, **annotation_payload}
        payload = {
            "graph_id": graph_id,
            "element_id": element_id,
            "element_kind": element_kind,
            "notation": notation,
            "payload_json": json.dumps(
                merged_annotation_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "revision": next_revision,
            "updated_at": now_orient(),
        }
        if existing and existing[0].get("@rid"):
            rid = str(existing[0]["@rid"])
            client.command(
                f"UPDATE {rid} MERGE {json.dumps(payload, ensure_ascii=False)} RETURN AFTER"
            )
        else:
            client.create_vertex("GraphAnnotation", {**payload, "created_at": now_orient()})
    return {
        "saved": True,
        "graph_id": graph_id,
        "element_id": element_id,
        "element_kind": element_kind,
        "notation": notation,
        "revision": next_revision,
    }


def save_graph_annotations_batch(
    client: OrientDBClient,
    request_payload: dict[str, object],
) -> dict[str, object]:
    items = request_payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("items должен содержать от 1 до 200 аннотаций.")
    results: list[dict[str, object]] = []
    with ANNOTATION_LOCK:
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Каждый элемент items должен быть JSON-объектом.")
            results.append(save_graph_annotation(client, item))
    return {"saved": len(results), "items": results}


def save_custom_graph(
    client: OrientDBClient,
    request_payload: dict[str, object],
) -> dict[str, object]:
    graph_id = required_string(request_payload, "graph_id")
    title = required_string(request_payload, "title")
    source_type = str(request_payload.get("source_type") or "manual")
    validate_identifier(graph_id, "graph_id")
    raw_nodes = request_payload.get("nodes")
    raw_edges = request_payload.get("edges")
    if not isinstance(raw_nodes, list) or not 1 <= len(raw_nodes) <= 200:
        raise ValueError("nodes должен содержать от 1 до 200 узлов.")
    if not isinstance(raw_edges, list) or len(raw_edges) > 500:
        raise ValueError("edges должен быть массивом не более чем из 500 ребер.")

    nodes = [normalize_custom_node(item) for item in raw_nodes]
    node_ids = {str(node["id"]) for node in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("Идентификаторы узлов должны быть уникальными.")
    edges = [normalize_custom_edge(item, node_ids=node_ids) for item in raw_edges]
    if len({str(edge["id"]) for edge in edges}) != len(edges):
        raise ValueError("Идентификаторы ребер должны быть уникальными.")
    client.save_graph_document(
        graph_id=graph_id,
        title=title,
        source_type=source_type,
        nodes=nodes,
        edges=edges,
    )
    return {
        "saved": True,
        "graph_id": graph_id,
        "run_id": f"graph:{graph_id}",
        "nodes": len(nodes),
        "edges": len(edges),
    }


def list_graph_groups(
    client: OrientDBClient,
    *,
    graph_id: str,
    notation: str,
) -> list[dict[str, object]]:
    validate_graph_scope(graph_id, notation)
    rows = orient_rows(
        client,
        "SELECT FROM GraphGroup "
        f"WHERE graph_id = '{sql_string(graph_id)}' "
        f"AND notation = '{sql_string(notation)}' ORDER BY created_at ASC",
    )
    return [graph_group_from_row(row) for row in rows]


def save_graph_group(
    client: OrientDBClient,
    request_payload: dict[str, object],
) -> dict[str, object]:
    graph_id = required_string(request_payload, "graph_id")
    notation = required_string(request_payload, "notation")
    group_id = required_string(request_payload, "group_id")
    title = required_string(request_payload, "title")
    revision = int_or_default(request_payload.get("revision"), -1)
    collapsed = request_payload.get("collapsed", False)
    validate_graph_scope(graph_id, notation)
    validate_identifier(group_id, "group_id")
    if len(title) > 200:
        raise ValueError("title группы превышает 200 символов.")
    if revision < 0:
        raise ValueError("revision должен быть неотрицательным целым числом.")
    if not isinstance(collapsed, bool):
        raise ValueError("collapsed должен быть логическим значением.")
    node_ids = normalize_identifier_list(
        request_payload.get("node_ids", []),
        field_name="node_ids",
        limit=MAX_GROUP_NODES,
    )
    child_group_ids = normalize_identifier_list(
        request_payload.get("child_group_ids", []),
        field_name="child_group_ids",
        limit=MAX_GROUP_CHILDREN,
    )
    if not node_ids and not child_group_ids:
        raise ValueError("Группа должна содержать узел или дочернюю группу.")

    with WORKSPACE_LOCK:
        rows = orient_rows(
            client,
            "SELECT FROM GraphGroup "
            f"WHERE graph_id = '{sql_string(graph_id)}' "
            f"AND notation = '{sql_string(notation)}' "
            f"AND group_id = '{sql_string(group_id)}' LIMIT 1",
        )
        current_revision = int_or_default(rows[0].get("revision"), 0) if rows else 0
        if revision != current_revision:
            raise ConflictError(
                f"Конфликт версии группы {group_id}: ожидалась {revision}, "
                f"текущая {current_revision}."
            )
        candidate = {
            "graph_id": graph_id,
            "notation": notation,
            "group_id": group_id,
            "title": title,
            "node_ids": node_ids,
            "child_group_ids": child_group_ids,
            "collapsed": collapsed,
            "revision": current_revision + 1,
        }
        groups = [
            group
            for group in list_graph_groups(client, graph_id=graph_id, notation=notation)
            if group["group_id"] != group_id
        ]
        groups.append(candidate)
        if len(groups) > MAX_GRAPH_GROUPS:
            raise ValueError(f"Граф может содержать не более {MAX_GRAPH_GROUPS} групп.")
        validate_group_hierarchy(groups, valid_node_ids=graph_node_ids(client, graph_id, notation))

        stored_payload = {
            "graph_id": graph_id,
            "notation": notation,
            "group_id": group_id,
            "title": title,
            "node_ids_json": compact_json(node_ids),
            "child_group_ids_json": compact_json(child_group_ids),
            "collapsed": collapsed,
            "revision": current_revision + 1,
            "updated_at": now_orient(),
        }
        if rows and rows[0].get("@rid"):
            client.command(
                f"UPDATE {rows[0]['@rid']} MERGE "
                f"{json.dumps(stored_payload, ensure_ascii=False)} RETURN AFTER"
            )
        else:
            client.create_vertex("GraphGroup", {**stored_payload, "created_at": now_orient()})
    saved_group = next(
        group
        for group in list_graph_groups(client, graph_id=graph_id, notation=notation)
        if group["group_id"] == group_id
    )
    return {"saved": True, **saved_group}


def delete_graph_group(
    client: OrientDBClient,
    *,
    graph_id: str,
    notation: str,
    group_id: str,
) -> dict[str, object]:
    validate_graph_scope(graph_id, notation)
    validate_identifier(group_id, "group_id")
    with WORKSPACE_LOCK:
        rows = orient_rows(
            client,
            "SELECT FROM GraphGroup "
            f"WHERE graph_id = '{sql_string(graph_id)}' "
            f"AND notation = '{sql_string(notation)}' "
            f"AND group_id = '{sql_string(group_id)}' LIMIT 1",
        )
        if not rows:
            return {"deleted": False, "group_id": group_id}
        groups = list_graph_groups(client, graph_id=graph_id, notation=notation)
        for parent in groups:
            child_ids = [item for item in parent["child_group_ids"] if item != group_id]
            if child_ids == parent["child_group_ids"]:
                continue
            if not child_ids and not parent["node_ids"]:
                raise ValueError(f"Сначала удалите родительскую группу {parent['group_id']}.")
            parent_rows = orient_rows(
                client,
                "SELECT @rid AS rid FROM GraphGroup "
                f"WHERE graph_id = '{sql_string(graph_id)}' "
                f"AND notation = '{sql_string(notation)}' "
                f"AND group_id = '{sql_string(str(parent['group_id']))}' LIMIT 1",
            )
            if parent_rows and parent_rows[0].get("rid"):
                update = {
                    "child_group_ids_json": compact_json(child_ids),
                    "revision": int_or_default(parent.get("revision"), 0) + 1,
                    "updated_at": now_orient(),
                }
                client.command(
                    f"UPDATE {parent_rows[0]['rid']} MERGE {json.dumps(update, ensure_ascii=False)}"
                )
        client.command(f"DELETE VERTEX {rows[0]['@rid']}")
    return {"deleted": True, "group_id": group_id}


def list_graph_templates(client: OrientDBClient) -> list[dict[str, object]]:
    rows = orient_rows(
        client,
        "SELECT template_id, name, description, notation, revision, created_at, updated_at "
        f"FROM GraphTemplate ORDER BY updated_at DESC LIMIT {MAX_GRAPH_TEMPLATES}",
    )
    return [graph_template_from_row(row, include_definition=False) for row in rows]


def get_graph_template(
    client: OrientDBClient,
    *,
    template_id: str,
) -> dict[str, object]:
    validate_identifier(template_id, "template_id")
    rows = orient_rows(
        client,
        f"SELECT FROM GraphTemplate WHERE template_id = '{sql_string(template_id)}' LIMIT 1",
    )
    if not rows:
        raise ValueError("Шаблон не найден.")
    return graph_template_from_row(rows[0], include_definition=True)


def save_graph_template(
    client: OrientDBClient,
    request_payload: dict[str, object],
) -> dict[str, object]:
    template_id = required_string(request_payload, "template_id")
    name = required_string(request_payload, "name")
    description = str(request_payload.get("description") or "").strip()
    notation = required_string(request_payload, "notation")
    revision = int_or_default(request_payload.get("revision"), -1)
    validate_identifier(template_id, "template_id")
    if notation not in SUPPORTED_NOTATIONS:
        raise ValueError(f"Неподдерживаемая нотация: {notation}")
    if len(name) > 200 or len(description) > 2000:
        raise ValueError("Название или описание шаблона превышает допустимую длину.")
    if revision < 0:
        raise ValueError("revision должен быть неотрицательным целым числом.")
    definition = normalize_template_definition(request_payload.get("definition"))

    with WORKSPACE_LOCK:
        rows = orient_rows(
            client,
            f"SELECT FROM GraphTemplate WHERE template_id = '{sql_string(template_id)}' LIMIT 1",
        )
        current_revision = int_or_default(rows[0].get("revision"), 0) if rows else 0
        if revision != current_revision:
            raise ConflictError(
                f"Конфликт версии шаблона {template_id}: ожидалась {revision}, "
                f"текущая {current_revision}."
            )
        if not rows and len(list_graph_templates(client)) >= MAX_GRAPH_TEMPLATES:
            raise ValueError(f"Разрешено хранить не более {MAX_GRAPH_TEMPLATES} шаблонов.")
        next_revision = current_revision + 1
        stored_payload = {
            "template_id": template_id,
            "name": name,
            "description": description,
            "notation": notation,
            "definition_json": compact_json(definition),
            "revision": next_revision,
            "updated_at": now_orient(),
        }
        if rows and rows[0].get("@rid"):
            client.command(
                f"UPDATE {rows[0]['@rid']} MERGE "
                f"{json.dumps(stored_payload, ensure_ascii=False)} RETURN AFTER"
            )
        else:
            client.create_vertex("GraphTemplate", {**stored_payload, "created_at": now_orient()})
    return {"saved": True, **get_graph_template(client, template_id=template_id)}


def delete_graph_template(
    client: OrientDBClient,
    *,
    template_id: str,
) -> dict[str, object]:
    validate_identifier(template_id, "template_id")
    with WORKSPACE_LOCK:
        rows = orient_rows(
            client,
            "SELECT @rid AS rid FROM GraphTemplate "
            f"WHERE template_id = '{sql_string(template_id)}' LIMIT 1",
        )
        if not rows:
            return {"deleted": False, "template_id": template_id}
        client.command(f"DELETE VERTEX {rows[0]['rid']}")
    return {"deleted": True, "template_id": template_id}


def list_graph_views(
    client: OrientDBClient,
    *,
    graph_id: str,
) -> list[dict[str, object]]:
    validate_graph_scope(graph_id, "flow")
    rows = orient_rows(
        client,
        "SELECT FROM GraphView "
        f"WHERE graph_id = '{sql_string(graph_id)}' "
        f"ORDER BY updated_at DESC LIMIT {MAX_GRAPH_VIEWS}",
    )
    return [graph_view_from_row(row) for row in rows]


def save_graph_view(
    client: OrientDBClient,
    request_payload: dict[str, object],
) -> dict[str, object]:
    graph_id = required_string(request_payload, "graph_id")
    view_id = required_string(request_payload, "view_id")
    name = required_string(request_payload, "name")
    revision = int_or_default(request_payload.get("revision"), -1)
    validate_graph_scope(graph_id, "flow")
    validate_identifier(view_id, "view_id")
    if len(name) > 200:
        raise ValueError("Название представления превышает 200 символов.")
    if revision < 0:
        raise ValueError("revision должен быть неотрицательным целым числом.")
    state = normalize_graph_view_state(request_payload.get("state"))

    with WORKSPACE_LOCK:
        rows = orient_rows(
            client,
            "SELECT FROM GraphView "
            f"WHERE graph_id = '{sql_string(graph_id)}' "
            f"AND view_id = '{sql_string(view_id)}' LIMIT 1",
        )
        current_revision = int_or_default(rows[0].get("revision"), 0) if rows else 0
        if revision != current_revision:
            raise ConflictError(
                f"Конфликт версии представления {view_id}: ожидалась {revision}, "
                f"текущая {current_revision}."
            )
        if not rows and len(list_graph_views(client, graph_id=graph_id)) >= MAX_GRAPH_VIEWS:
            raise ValueError(f"Для карты разрешено не более {MAX_GRAPH_VIEWS} представлений.")
        stored_payload = {
            "graph_id": graph_id,
            "view_id": view_id,
            "name": name,
            "state_json": compact_json(state),
            "revision": current_revision + 1,
            "updated_at": now_orient(),
        }
        if rows and rows[0].get("@rid"):
            client.command(
                f"UPDATE {rows[0]['@rid']} MERGE "
                f"{json.dumps(stored_payload, ensure_ascii=False)} RETURN AFTER"
            )
        else:
            client.create_vertex("GraphView", {**stored_payload, "created_at": now_orient()})
    saved = next(
        view for view in list_graph_views(client, graph_id=graph_id) if view["view_id"] == view_id
    )
    return {"saved": True, **saved}


def delete_graph_view(
    client: OrientDBClient,
    *,
    graph_id: str,
    view_id: str,
) -> dict[str, object]:
    validate_graph_scope(graph_id, "flow")
    validate_identifier(view_id, "view_id")
    with WORKSPACE_LOCK:
        rows = orient_rows(
            client,
            "SELECT @rid AS rid FROM GraphView "
            f"WHERE graph_id = '{sql_string(graph_id)}' "
            f"AND view_id = '{sql_string(view_id)}' LIMIT 1",
        )
        if not rows:
            return {"deleted": False, "view_id": view_id}
        client.command(f"DELETE VERTEX {rows[0]['rid']}")
    return {"deleted": True, "view_id": view_id}


def list_node_occurrences(
    client: OrientDBClient,
    *,
    notation: str,
) -> list[dict[str, object]]:
    if notation not in SUPPORTED_NOTATIONS:
        raise ValueError(f"Неподдерживаемая нотация: {notation}")
    custom_rows = orient_rows(
        client,
        f"SELECT graph_id, node_id, label FROM GraphNode LIMIT {MAX_OCCURRENCE_ROWS}",
    )
    annotation_rows = orient_rows(
        client,
        "SELECT graph_id, element_id, payload_json FROM GraphAnnotation "
        "WHERE element_kind = 'node' "
        f"AND notation = '{sql_string(notation)}' LIMIT {MAX_OCCURRENCE_ROWS}",
    )
    annotated_labels: dict[tuple[str, str], str] = {}
    for row in annotation_rows:
        payload = json_object(row.get("payload_json"))
        label = str(payload.get("label") or "").strip()
        if label:
            key = (str(row.get("graph_id") or ""), str(row.get("element_id") or ""))
            annotated_labels[key] = label

    entries: list[tuple[str, str]] = []
    for row in custom_rows:
        graph_id = f"graph:{row.get('graph_id', '')}"
        node_id = str(row.get("node_id") or "")
        label = annotated_labels.get((graph_id, node_id), str(row.get("label") or ""))
        if graph_id != "graph:" and label.strip():
            entries.append((graph_id, label.strip()))
    search_rows = orient_rows(
        client,
        f"SELECT run_id, title FROM SearchResult LIMIT {MAX_OCCURRENCE_ROWS}",
    )
    entries.extend(
        (f"run:{row.get('run_id', '')}", str(row.get("title") or "").strip())
        for row in search_rows
        if row.get("run_id") and str(row.get("title") or "").strip()
    )

    maps_by_key: dict[str, set[str]] = {}
    labels_by_key: dict[str, str] = {}
    for graph_id, label in entries:
        key = normalize_occurrence_label(label)
        if not key:
            continue
        maps_by_key.setdefault(key, set()).add(graph_id)
        labels_by_key.setdefault(key, label)
    return [
        {
            "key": key,
            "label": labels_by_key[key],
            "map_count": len(graph_ids),
            "map_ids": sorted(graph_ids),
        }
        for key, graph_ids in sorted(
            maps_by_key.items(),
            key=lambda item: (-len(item[1]), labels_by_key[item[0]].casefold()),
        )
        if len(graph_ids) > 1
    ]


def custom_graph_payload(
    *,
    client: OrientDBClient,
    graph_id: str,
    notation: str,
) -> dict[str, object]:
    documents = orient_rows(
        client,
        f"SELECT FROM GraphDocument WHERE graph_id = '{sql_string(graph_id)}' LIMIT 1",
    )
    if not documents:
        return empty_graph(notation=notation, graph_id=f"graph:{graph_id}")
    node_rows = orient_rows(
        client,
        f"SELECT FROM GraphNode WHERE graph_id = '{sql_string(graph_id)}'",
    )
    edge_rows = orient_rows(
        client,
        f"SELECT FROM GraphConnection WHERE graph_id = '{sql_string(graph_id)}'",
    )
    nodes = [custom_node_from_row(row, notation=notation) for row in node_rows]
    edges = [custom_edge_from_row(row, notation=notation) for row in edge_rows]
    payload_graph_id = f"graph:{graph_id}"
    annotations = annotations_for_graph(
        client,
        graph_id=payload_graph_id,
        notation=notation,
    )
    nodes = [
        apply_node_annotation(node, annotations.get(("node", node.id)), notation) for node in nodes
    ]
    edges = [
        apply_edge_annotation(edge, annotations.get(("edge", edge.id)), notation) for edge in edges
    ]
    document = documents[0]
    return {
        "graph_id": payload_graph_id,
        "title": str(document.get("title") or graph_id),
        "notation": notation,
        "source": {
            "database": client.database,
            "root_class": "GraphDocument",
            "graph_id": graph_id,
            "source_type": document.get("source_type", "manual"),
        },
        "nodes": [node_to_dict(node) for node in nodes],
        "edges": [edge_to_dict(edge) for edge in edges],
    }


def normalize_custom_node(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Каждый узел должен быть JSON-объектом.")
    node_id = required_string(value, "id")
    validate_identifier(node_id, "node.id")
    shape = str(value.get("shape") or "rounded_rectangle")
    if shape not in SUPPORTED_SHAPES:
        raise ValueError(f"Узел {node_id} содержит неподдерживаемую форму.")
    image_data = str(value.get("image_data") or value.get("imageUrl") or "")
    if image_data and (len(image_data) > 1_000_000 or not is_allowed_image_value(image_data)):
        raise ValueError(f"Узел {node_id} содержит некорректное изображение.")
    position_3d = position_3d_value(
        value.get("position3d"),
        {"x": 0.0, "y": 0.0, "z": 0.0},
    )
    created_at = str(value.get("created_at") or value.get("createdAt") or "")
    ended_at = str(value.get("ended_at") or value.get("endedAt") or "")
    validate_temporal_interval(created_at, ended_at)
    return {
        "id": node_id,
        "label": str(value.get("label") or node_id)[:1000],
        "type": str(value.get("type") or "process")[:100],
        "shape": shape,
        "created_at": created_at,
        "ended_at": ended_at,
        "x": int_or_default(value.get("x"), 0),
        "y": int_or_default(value.get("y"), 0),
        "position3d": position_3d,
        "image_data": image_data,
        "properties": list_value(value.get("properties"))[:50],
    }


def normalize_custom_edge(value: object, *, node_ids: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Каждое ребро должно быть JSON-объектом.")
    edge_id = required_string(value, "id")
    source = required_string(value, "source")
    target = required_string(value, "target")
    for identifier, field_name in ((edge_id, "edge.id"), (source, "source"), (target, "target")):
        validate_identifier(identifier, field_name)
    if source not in node_ids or target not in node_ids:
        raise ValueError(f"Ребро {edge_id} ссылается на отсутствующий узел.")
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": str(value.get("type") or "follow")[:100],
        "label": str(value.get("label") or "")[:1000],
        "properties": list_value(value.get("properties"))[:50],
    }


def normalize_template_definition(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("definition должен быть JSON-объектом.")
    raw_nodes = value.get("nodes")
    raw_edges = value.get("edges", [])
    raw_groups = value.get("groups", [])
    if not isinstance(raw_nodes, list) or not 1 <= len(raw_nodes) <= 200:
        raise ValueError("Шаблон должен содержать от 1 до 200 узлов.")
    if not isinstance(raw_edges, list) or len(raw_edges) > 500:
        raise ValueError("Шаблон может содержать не более 500 ребер.")
    if not isinstance(raw_groups, list) or len(raw_groups) > MAX_GRAPH_GROUPS:
        raise ValueError(f"Шаблон может содержать не более {MAX_GRAPH_GROUPS} групп.")

    nodes = [normalize_custom_node(item) for item in raw_nodes]
    node_ids = {str(node["id"]) for node in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("Идентификаторы узлов шаблона должны быть уникальными.")
    for node in nodes:
        validate_properties(node["properties"])
    edges = [normalize_custom_edge(item, node_ids=node_ids) for item in raw_edges]
    if len({str(edge["id"]) for edge in edges}) != len(edges):
        raise ValueError("Идентификаторы ребер шаблона должны быть уникальными.")
    for edge in edges:
        validate_properties(edge["properties"])

    groups = [normalize_template_group(item) for item in raw_groups]
    if len({str(group["group_id"]) for group in groups}) != len(groups):
        raise ValueError("Идентификаторы групп шаблона должны быть уникальными.")
    validate_group_hierarchy(groups, valid_node_ids=node_ids)
    return {"nodes": nodes, "edges": edges, "groups": groups}


def normalize_template_group(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Каждая группа шаблона должна быть JSON-объектом.")
    group_id = required_string(value, "group_id")
    title = required_string(value, "title")
    collapsed = value.get("collapsed", False)
    validate_identifier(group_id, "group_id")
    if len(title) > 200:
        raise ValueError("title группы превышает 200 символов.")
    if not isinstance(collapsed, bool):
        raise ValueError("collapsed должен быть логическим значением.")
    node_ids = normalize_identifier_list(
        value.get("node_ids", []),
        field_name="node_ids",
        limit=MAX_GROUP_NODES,
    )
    child_group_ids = normalize_identifier_list(
        value.get("child_group_ids", []),
        field_name="child_group_ids",
        limit=MAX_GROUP_CHILDREN,
    )
    if not node_ids and not child_group_ids:
        raise ValueError("Группа шаблона не может быть пустой.")
    return {
        "group_id": group_id,
        "title": title,
        "node_ids": node_ids,
        "child_group_ids": child_group_ids,
        "collapsed": collapsed,
    }


def validate_group_hierarchy(
    groups: list[dict[str, object]],
    *,
    valid_node_ids: set[str],
) -> None:
    groups_by_id = {str(group["group_id"]): group for group in groups}
    node_owners: dict[str, str] = {}
    group_parents: dict[str, str] = {}
    for group_id, group in groups_by_id.items():
        node_ids = [str(item) for item in list_value(group.get("node_ids"))]
        child_ids = [str(item) for item in list_value(group.get("child_group_ids"))]
        missing_nodes = sorted(set(node_ids) - valid_node_ids)
        if missing_nodes:
            raise ValueError(
                f"Группа {group_id} ссылается на отсутствующий узел {missing_nodes[0]}."
            )
        for node_id in node_ids:
            owner = node_owners.setdefault(node_id, group_id)
            if owner != group_id:
                raise ValueError(f"Узел {node_id} уже входит в группу {owner}.")
        for child_id in child_ids:
            if child_id == group_id:
                raise ValueError(f"Группа {group_id} не может содержать саму себя.")
            if child_id not in groups_by_id:
                raise ValueError(f"Дочерняя группа {child_id} не существует.")
            parent = group_parents.setdefault(child_id, group_id)
            if parent != group_id:
                raise ValueError(f"Группа {child_id} уже входит в группу {parent}.")

    state: dict[str, int] = {}

    def visit(group_id: str) -> None:
        if state.get(group_id) == 1:
            raise ValueError("Иерархия групп содержит цикл.")
        if state.get(group_id) == 2:
            return
        state[group_id] = 1
        for child_id in list_value(groups_by_id[group_id].get("child_group_ids")):
            visit(str(child_id))
        state[group_id] = 2

    for group_id in groups_by_id:
        visit(group_id)


def normalize_identifier_list(value: object, *, field_name: str, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{field_name} должен быть массивом не более чем из {limit} элементов.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Каждый элемент {field_name} должен быть непустой строкой.")
        identifier = item.strip()
        validate_identifier(identifier, field_name)
        if identifier in result:
            raise ValueError(f"{field_name} содержит повторяющийся идентификатор.")
        result.append(identifier)
    return result


def validate_graph_scope(graph_id: str, notation: str) -> None:
    if not graph_id:
        raise ValueError("Поле graph_id обязательно.")
    validate_identifier(graph_id, "graph_id")
    if not graph_id.startswith(("run:", "graph:")):
        raise ValueError("graph_id должен начинаться с run: или graph:.")
    if notation not in SUPPORTED_NOTATIONS:
        raise ValueError(f"Неподдерживаемая нотация: {notation}")


def graph_node_ids(client: OrientDBClient, graph_id: str, notation: str) -> set[str]:
    if graph_id.startswith("run:"):
        payload = run_graph_payload(
            client=client,
            run_id=graph_id.removeprefix("run:"),
            notation=notation,
            limit=12,
        )
    elif graph_id.startswith("graph:"):
        payload = custom_graph_payload(
            client=client,
            graph_id=graph_id.removeprefix("graph:"),
            notation=notation,
        )
    else:
        return set()
    return {
        str(item["id"])
        for item in list_value(payload.get("nodes"))
        if isinstance(item, dict) and item.get("id") and not str(item["id"]).startswith("__")
    }


def graph_group_from_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "graph_id": str(row.get("graph_id") or ""),
        "notation": str(row.get("notation") or "flow"),
        "group_id": str(row.get("group_id") or ""),
        "title": str(row.get("title") or "Группа"),
        "node_ids": [str(item) for item in json_list(row.get("node_ids_json"))],
        "child_group_ids": [str(item) for item in json_list(row.get("child_group_ids_json"))],
        "collapsed": bool(row.get("collapsed", False)),
        "revision": int_or_default(row.get("revision"), 0),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def graph_template_from_row(
    row: dict[str, object],
    *,
    include_definition: bool,
) -> dict[str, object]:
    result = {
        "template_id": str(row.get("template_id") or ""),
        "name": str(row.get("name") or "Шаблон"),
        "description": str(row.get("description") or ""),
        "notation": str(row.get("notation") or "flow"),
        "revision": int_or_default(row.get("revision"), 0),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }
    if include_definition:
        result["definition"] = json_object(row.get("definition_json"))
    return result


def graph_view_from_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "graph_id": str(row.get("graph_id") or ""),
        "view_id": str(row.get("view_id") or ""),
        "name": str(row.get("name") or "Представление"),
        "state": json_object(row.get("state_json")),
        "revision": int_or_default(row.get("revision"), 0),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def normalize_graph_view_state(value: object) -> dict[str, object]:
    state = json_object(value)
    allowed = {
        "notation",
        "view_mode",
        "metric_mode",
        "inverted_background",
        "hidden_node_types",
        "hidden_edge_types",
        "hidden_levels",
        "attribute_filters",
        "collapsed_branches",
        "viewport",
    }
    unknown = set(state) - allowed
    if unknown:
        raise ValueError("Неизвестные поля представления: " + ", ".join(sorted(unknown)))
    notation = str(state.get("notation") or "flow")
    view_mode = str(state.get("view_mode") or "2d")
    metric_mode = str(state.get("metric_mode") or "planned")
    if notation not in SUPPORTED_NOTATIONS:
        raise ValueError(f"Неподдерживаемая нотация: {notation}")
    if view_mode not in {"2d", "3d"}:
        raise ValueError("view_mode должен быть равен 2d или 3d.")
    if metric_mode not in {"planned", "actual"}:
        raise ValueError("metric_mode должен быть равен planned или actual.")
    inverted_background = state.get("inverted_background", False)
    if not isinstance(inverted_background, bool):
        raise ValueError("inverted_background должен быть логическим значением.")
    hidden_levels = state.get("hidden_levels", [])
    if (
        not isinstance(hidden_levels, list)
        or len(hidden_levels) > 100
        or any(
            not isinstance(level, int) or isinstance(level, bool) or level < 0
            for level in hidden_levels
        )
    ):
        raise ValueError("hidden_levels должен содержать неотрицательные целые числа.")
    filters = json_object(state.get("attribute_filters"))
    if set(filters) - {"status", "region", "organization", "year"}:
        raise ValueError("attribute_filters содержит неизвестные поля.")
    normalized_filters = {
        field: str(filters.get(field) or "").strip()[:200]
        for field in ("status", "region", "organization", "year")
    }
    viewport = json_object(state.get("viewport"))
    normalized_viewport: dict[str, float] = {}
    if viewport:
        for field in ("x", "y", "zoom"):
            raw = viewport.get(field)
            if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not math.isfinite(raw):
                raise ValueError("viewport должен содержать конечные x, y и zoom.")
            normalized_viewport[field] = float(raw)
        if not 0.05 <= normalized_viewport["zoom"] <= 10:
            raise ValueError("viewport.zoom находится вне допустимого диапазона.")
    normalized = {
        "notation": notation,
        "view_mode": view_mode,
        "metric_mode": metric_mode,
        "inverted_background": inverted_background,
        "hidden_node_types": normalize_identifier_list(
            state.get("hidden_node_types", []),
            field_name="hidden_node_types",
            limit=100,
        ),
        "hidden_edge_types": normalize_identifier_list(
            state.get("hidden_edge_types", []),
            field_name="hidden_edge_types",
            limit=100,
        ),
        "hidden_levels": sorted(set(hidden_levels)),
        "attribute_filters": normalized_filters,
        "collapsed_branches": normalize_identifier_list(
            state.get("collapsed_branches", []),
            field_name="collapsed_branches",
            limit=200,
        ),
        "viewport": normalized_viewport,
    }
    if len(compact_json(normalized).encode("utf-8")) > MAX_VIEW_STATE_BYTES:
        raise ValueError("Состояние представления превышает допустимый размер.")
    return normalized


def normalize_occurrence_label(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def custom_node_from_row(row: dict[str, object], *, notation: str) -> ApiNode:
    return runtime_node(
        node_id=str(row.get("node_id") or row.get("@rid") or ""),
        label=str(row.get("label") or ""),
        node_type=str(row.get("node_type") or "process"),
        stored_shape=str(row.get("shape") or "rounded_rectangle"),
        x=int_or_default(row.get("position_x"), 0),
        y=int_or_default(row.get("position_y"), 0),
        notation=notation,
        data={
            "class": "GraphNode",
            "created_at": row.get("created_at", ""),
            "ended_at": row.get("ended_at", ""),
            "imageUrl": row.get("image_data", ""),
            "properties": json_list(row.get("properties_json")),
            "position3d": {
                "x": float_or_default(row.get("position_3d_x"), 0.0),
                "y": float_or_default(row.get("position_3d_y"), 0.0),
                "z": float_or_default(row.get("position_3d_z"), 0.0),
            },
        },
    )


def custom_edge_from_row(row: dict[str, object], *, notation: str) -> ApiEdge:
    edge = runtime_edge(
        str(row.get("edge_id") or row.get("@rid") or ""),
        str(row.get("source_id") or ""),
        str(row.get("target_id") or ""),
        str(row.get("edge_type") or "follow"),
        str(row.get("label") or ""),
        notation,
    )
    return replace(edge, data={"properties": json_list(row.get("properties_json"))})


def graph_element_exists(
    client: OrientDBClient,
    *,
    graph_id: str,
    element_kind: str,
    element_id: str,
    notation: str,
) -> bool:
    if graph_id.startswith("run:"):
        payload = run_graph_payload(
            client=client,
            run_id=graph_id.removeprefix("run:"),
            notation=notation,
            limit=12,
        )
    elif graph_id.startswith("graph:"):
        payload = custom_graph_payload(
            client=client,
            graph_id=graph_id.removeprefix("graph:"),
            notation=notation,
        )
    else:
        return False
    collection = payload.get("nodes" if element_kind == "node" else "edges", [])
    return isinstance(collection, list) and any(
        isinstance(item, dict) and item.get("id") == element_id for item in collection
    )


def annotations_for_graph(
    client: OrientDBClient,
    *,
    graph_id: str,
    notation: str,
) -> dict[tuple[str, str], GraphAnnotationRecord]:
    try:
        rows = orient_rows(
            client,
            f"SELECT FROM GraphAnnotation WHERE graph_id = '{sql_string(graph_id)}'",
        )
    except RuntimeError as exc:
        if "Class not found: GraphAnnotation" in str(exc):
            return {}
        raise
    annotations: dict[tuple[str, str], GraphAnnotationRecord] = {}
    for row in rows:
        row_notation = str(row.get("notation") or "")
        if row_notation != notation and not (not row_notation and notation == "flow"):
            continue
        element_kind = str(row.get("element_kind") or "")
        element_id = str(row.get("element_id") or "")
        payload = json_object(row.get("payload_json"))
        if element_kind and element_id and payload:
            annotations[(element_kind, element_id)] = GraphAnnotationRecord(
                payload=payload,
                revision=int_or_default(row.get("revision"), 0),
            )
    return annotations


def apply_node_annotation(
    node: ApiNode,
    annotation: GraphAnnotationRecord | None,
    notation: str,
) -> ApiNode:
    base_created_at = str(
        node.data.get("created_at")
        or node.data.get("finished_at")
        or node.data.get("published_at")
        or "",
    )
    base_ended_at = str(node.data.get("ended_at") or node.data.get("finished_at") or "")
    base_image_url = str(node.data.get("imageUrl") or node.data.get("image_url") or "")
    base_properties = list_value(node.data.get("properties"))
    base_position_3d = position_3d_value(
        node.data.get("position3d"),
        default_3d_position(node),
    )
    base = {
        "label": node.label,
        "shape": node.shape,
        "position": node.position,
        "imageUrl": base_image_url,
        "createdAt": base_created_at,
        "endedAt": base_ended_at,
        "properties": base_properties,
        "position3d": base_position_3d,
    }
    data = {
        **node.data,
        "base": base,
        "created_at": base_created_at,
        "ended_at": base_ended_at,
        "imageUrl": base_image_url,
        "properties": base_properties,
        "position3d": base_position_3d,
        "annotation_revision": 0,
    }
    if not annotation:
        return replace(node, data=data)

    payload = annotation.payload
    label = string_value(payload.get("label"), node.label)
    shape = string_value(payload.get("shape"), node.shape)
    position = position_value(payload.get("position"), node.position)
    position_3d = position_3d_value(payload.get("position3d"), base_position_3d)
    image_url = string_value(
        payload.get("imageUrl") or payload.get("image_url"),
        base_image_url,
    )
    created_at = string_value(
        payload.get("createdAt") if "createdAt" in payload else payload.get("created_at"),
        base_created_at,
    )
    ended_at = string_value(
        payload.get("endedAt") if "endedAt" in payload else payload.get("ended_at"),
        base_ended_at,
    )
    properties = (
        list_value(payload.get("properties")) if "properties" in payload else base_properties
    )
    data.update(
        {
            "annotation": payload,
            "annotation_revision": annotation.revision,
            "created_at": created_at,
            "ended_at": ended_at,
            "imageUrl": image_url,
            "properties": properties,
            "position3d": position_3d,
        },
    )
    return replace(
        node,
        label=label,
        shape=shape,
        position=position,
        style=merge_style(stored_style={}, shape=shape, node_type=node.type, notation=notation),
        data=data,
    )


def apply_edge_annotation(
    edge: ApiEdge,
    annotation: GraphAnnotationRecord | None,
    notation: str,
) -> ApiEdge:
    base_properties = list_value(edge.data.get("properties"))
    base = {
        "label": edge.label,
        "edgeType": edge.type,
        "properties": base_properties,
    }
    data = {
        **edge.data,
        "base": base,
        "edgeType": edge.type,
        "properties": base_properties,
        "annotation_revision": 0,
    }
    if not annotation:
        return replace(edge, data=data)

    payload = annotation.payload
    edge_type = string_value(payload.get("edgeType") or payload.get("type"), edge.type)
    label = string_value(payload.get("label"), edge.label)
    properties = (
        list_value(payload.get("properties")) if "properties" in payload else base_properties
    )
    data.update(
        {
            "annotation": payload,
            "annotation_revision": annotation.revision,
            "edgeType": edge_type,
            "properties": properties,
        },
    )
    return replace(
        edge,
        type=edge_type,
        label=label,
        style=merge_edge_style(stored_style={}, edge_type=edge_type, notation=notation),
        data=data,
    )


def news_node_id(link: dict[str, object]) -> str:
    value = str(
        link.get("result_id") or link.get("@rid") or link.get("url") or link.get("title") or ""
    )
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
            "/api/graph/custom/{graph_id}?notation=flow",
            "POST /api/graph/annotations",
            "POST /api/graph/annotations/batch",
            "POST /api/graphs",
            "GET|POST /api/graph/groups",
            "DELETE /api/graph/groups/{group_id}",
            "GET /api/graph/node-occurrences",
            "GET|POST /api/graph/views",
            "DELETE /api/graph/views/{view_id}",
            "GET|POST /api/graph/templates",
            "GET|DELETE /api/graph/templates/{template_id}",
        ],
        "notations": list(SUPPORTED_NOTATIONS),
        "storage": {
            "primary": [
                "SearchRun",
                "SearchResult",
                "NewsLink",
                "Source",
                "Topic",
                "ModelRun",
            ],
            "ui_state": ["GraphAnnotation", "GraphGroup", "GraphTemplate"],
            "custom_graph": ["GraphDocument", "GraphNode", "GraphConnection"],
        },
        "node": {
            "id": "stable runtime node id",
            "label": "human-readable label",
            "type": "semantic node type",
            "shape": "notation-derived shape",
            "position": {"x": "layout x", "y": "layout y"},
            "position3d": {"x": "space x", "y": "space y", "z": "space z"},
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
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def required_string(payload: dict[str, object], key: str) -> str:
    raw_value = payload.get(key)
    if not isinstance(raw_value, str):
        raise ValueError(f"Поле {key} должно быть строкой.")
    value = raw_value.strip()
    if not value:
        raise ValueError(f"Поле {key} обязательно.")
    return value


def json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def string_value(value: object, default: str) -> str:
    if value is None:
        return default
    return str(value)


def position_value(value: object, default: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        return default
    try:
        return {
            "x": round(float(value.get("x", default["x"]))),
            "y": round(float(value.get("y", default["y"]))),
        }
    except (TypeError, ValueError):
        return default


def position_3d_value(
    value: object,
    default: dict[str, float],
) -> dict[str, float]:
    if not isinstance(value, dict):
        return default
    return {axis: float_or_default(value.get(axis), default[axis]) for axis in ("x", "y", "z")}


def default_3d_position(node: ApiNode) -> dict[str, float]:
    depth = int(stable_hash(node.id)[:4], 16) % 51 - 25
    return {
        "x": round(node.position["x"] / 3, 2),
        "y": round(-node.position["y"] / 3, 2),
        "z": float(depth),
    }


def list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def validate_identifier(value: str, field_name: str) -> None:
    if len(value) > 240 or any(ord(character) < 32 for character in value):
        raise ValueError(f"Поле {field_name} имеет недопустимый формат.")


def validate_annotation_payload(element_kind: str, payload: dict[str, object]) -> None:
    allowed = {"label", "properties"}
    if element_kind == "node":
        allowed.update({"shape", "imageUrl", "createdAt", "endedAt", "position", "position3d"})
    else:
        allowed.add("edgeType")
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("Неизвестные поля аннотации: " + ", ".join(sorted(unknown)))
    if "label" in payload and len(str(payload["label"])) > 1000:
        raise ValueError("label превышает 1000 символов.")
    if "shape" in payload and payload["shape"] not in SUPPORTED_SHAPES:
        raise ValueError("Указана неподдерживаемая форма узла.")
    validate_image_value(payload.get("imageUrl"))
    validate_properties(payload.get("properties", []))
    validate_temporal_interval(payload.get("createdAt"), payload.get("endedAt"))
    validate_coordinates(payload.get("position"), axes=("x", "y"), field_name="position")
    validate_coordinates(
        payload.get("position3d"),
        axes=("x", "y", "z"),
        field_name="position3d",
    )


def validate_image_value(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) > 1_000_000:
        raise ValueError("Некорректное изображение или превышен лимит 1 МБ.")
    if value and not is_allowed_image_value(value):
        raise ValueError("Изображение должно быть HTTP(S)-URL или data:image.")


def validate_temporal_interval(created_at: object, ended_at: object) -> None:
    parsed: dict[str, datetime] = {}
    for field, value in (("createdAt", created_at), ("endedAt", ended_at)):
        if value is None or value == "":
            continue
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError(f"{field} должен быть строкой даты ISO 8601.")
        timestamp = parse_datetime(value)
        if timestamp is None:
            raise ValueError(f"{field} должен содержать дату ISO 8601.")
        parsed[field] = timestamp
    if (
        parsed.get("createdAt")
        and parsed.get("endedAt")
        and parsed["endedAt"] < parsed["createdAt"]
    ):
        raise ValueError("endedAt не может быть раньше createdAt.")


def validate_properties(properties: object) -> None:
    if not isinstance(properties, list) or len(properties) > 50:
        raise ValueError("properties должен быть массивом не более чем из 50 элементов.")
    for item in properties:
        if not isinstance(item, dict):
            raise ValueError("Каждый property должен быть JSON-объектом.")
        if len(str(item.get("key") or "")) > 200 or len(str(item.get("value") or "")) > 2000:
            raise ValueError("Свойство превышает допустимую длину.")


def validate_coordinates(value: object, *, axes: tuple[str, ...], field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} должен быть JSON-объектом.")
    try:
        coordinates = tuple(float(value[axis]) for axis in axes)
    except (KeyError, TypeError, ValueError) as exc:
        axis_list = ", ".join(axes[:-1]) + f" и {axes[-1]}"
        raise ValueError(f"{field_name} должен содержать числовые {axis_list}.") from exc
    if not all(math.isfinite(coordinate) for coordinate in coordinates):
        raise ValueError(f"Координаты {field_name} должны быть конечными числами.")


def is_allowed_image_value(value: str) -> bool:
    if value.startswith("data:image/"):
        return ";base64," in value[:100]
    parsed = urllib.parse.urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def allowed_origin(origin: str | None) -> str:
    if not origin:
        return ""
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return origin
    return ""


def sql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
