from __future__ import annotations

import json
import math
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from electromotiv_pipeline.models import RankedLink, SavedRecord


class OrientDBClient:
    def __init__(self, *, base_url: str, database: str, auth_header: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.database = database
        self.auth_header = auth_header

    def command(self, sql: str, timeout_seconds: int = 30) -> dict[str, object]:
        socket.setdefaulttimeout(timeout_seconds)
        database = urllib.parse.quote(self.database, safe="")
        request = urllib.request.Request(
            f"{self.base_url}/command/{database}/sql",
            data=sql.encode("utf-8"),
            headers={
                "Authorization": self.auth_header,
                "Content-Type": "text/plain; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return decode_json_response(response.read(), context="OrientDB command")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OrientDB вернул HTTP {exc.code}: {error_body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"OrientDB недоступна: {exc}") from exc

    def request_server(
        self,
        path: str,
        *,
        method: str = "GET",
        timeout_seconds: int = 30,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": self.auth_header},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return decode_json_response(response.read(), context="OrientDB server API")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OrientDB вернул HTTP {exc.code}: {error_body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"OrientDB недоступна: {exc}") from exc

    def ensure_database(self) -> None:
        database = urllib.parse.quote(self.database, safe="")
        payload = self.request_server("/listDatabases")
        databases = payload.get("databases", [])
        if isinstance(databases, list) and self.database in {str(item) for item in databases}:
            return
        self.request_server(f"/database/{database}/plocal", method="POST", timeout_seconds=120)

    def ensure_schema(self, schema_path: Path) -> None:
        self.ensure_database()
        statements = split_sql_statements(schema_path.read_text(encoding="utf-8"))
        schema_statements = [
            statement
            for statement in statements
            if not statement.upper().startswith("CREATE INDEX")
        ]
        index_statements = [
            statement for statement in statements if statement.upper().startswith("CREATE INDEX")
        ]
        for statement in schema_statements:
            self.apply_schema_statement(statement)
        self.migrate_legacy_records()
        for statement in index_statements:
            self.apply_schema_statement(statement)

    def apply_schema_statement(self, statement: str) -> None:
        try:
            self.command(statement)
        except RuntimeError as exc:
            if "already exists" in str(exc):
                return
            raise

    def migrate_legacy_records(self) -> None:
        source_rows = response_rows(
            self.command("SELECT @rid AS rid, name, domain, source_key FROM Source")
        )
        used_source_keys = {
            str(row.get("source_key")) for row in source_rows if row.get("source_key")
        }
        for row in source_rows:
            if row.get("source_key"):
                continue
            rid = str(row.get("rid") or "")
            if not rid:
                continue
            name = str(row.get("name") or "unknown").strip().casefold()
            domain = str(row.get("domain") or "").strip().casefold()
            source_key = f"{name}|{domain}"
            if source_key in used_source_keys:
                source_key = f"{source_key}|legacy:{rid.removeprefix('#')}"
            used_source_keys.add(source_key)
            self.command(
                f"UPDATE {rid} MERGE {json.dumps({'source_key': source_key}, ensure_ascii=False)}"
            )

        annotation_rows = response_rows(
            self.command(
                "SELECT @rid AS rid, graph_id, element_id, element_kind, notation, revision "
                "FROM GraphAnnotation"
            )
        )
        used_annotation_keys: set[tuple[str, str, str, str]] = set()
        for row in annotation_rows:
            rid = str(row.get("rid") or "")
            notation = str(row.get("notation") or "flow")
            key = (
                str(row.get("graph_id") or ""),
                notation,
                str(row.get("element_kind") or ""),
                str(row.get("element_id") or ""),
            )
            if key in used_annotation_keys:
                notation = f"legacy-{rid.removeprefix('#').replace(':', '-')}"
                key = (key[0], notation, key[2], key[3])
            used_annotation_keys.add(key)
            updates: dict[str, object] = {}
            if row.get("notation") != notation:
                updates["notation"] = notation
            if row.get("revision") is None:
                updates["revision"] = 1
            if rid and updates:
                self.command(f"UPDATE {rid} MERGE {json.dumps(updates, ensure_ascii=False)}")

    def save_ranked_links(
        self,
        *,
        query: str,
        run_id: str,
        model: str,
        links: list[RankedLink],
        sources_count: int,
        candidates_count: int,
        started_at: str = "",
    ) -> list[SavedRecord]:
        run_rid = self.create_search_run(
            run_id=run_id,
            query=query,
            model=model,
            sources_count=sources_count,
            candidates_count=candidates_count,
            ranked_count=len(links),
            saved_count=0,
            status="running",
            started_at=started_at,
        )
        saved: list[SavedRecord] = []
        try:
            model_run_rid = self.create_model_run(
                run_id=run_id,
                model=model,
                raw_response=links[0].llm_raw_response if links else "",
            )
            topic_rid = self.create_or_get_vertex("Topic", {"name": query})
            if run_rid and topic_rid:
                self.create_edge("About", run_rid, topic_rid)
            if run_rid and model_run_rid:
                self.create_edge("AnalyzedBy", run_rid, model_run_rid)

            for link in links:
                news_rid = self.create_or_get_news_link(link)
                result_rid = self.create_search_result(link)
                source_rid = self.create_or_get_source(link)
                if run_rid and result_rid:
                    self.create_edge("Found", run_rid, result_rid)
                if result_rid and news_rid:
                    self.create_edge("References", result_rid, news_rid)
                if result_rid and source_rid:
                    self.create_edge("FromSource", result_rid, source_rid)
                if model_run_rid and result_rid:
                    self.create_edge("AnalyzedAs", model_run_rid, result_rid)
                saved.append(SavedRecord(url=link.url, rid=result_rid))
        except Exception as exc:
            self.update_search_run_status(
                run_id=run_id,
                status="failed",
                saved_count=len(saved),
                error=str(exc),
            )
            raise
        self.update_search_run_status(
            run_id=run_id,
            status="success",
            saved_count=len(saved),
        )
        return saved

    def create_search_run(
        self,
        *,
        run_id: str,
        query: str,
        model: str,
        sources_count: int,
        candidates_count: int,
        ranked_count: int,
        saved_count: int,
        status: str,
        error: str = "",
        started_at: str = "",
    ) -> str:
        payload = {
            "run_id": run_id,
            "query": query,
            "model": model,
            "started_at": orient_datetime(started_at) or now_orient(),
            "finished_at": now_orient(),
            "sources_count": sources_count,
            "candidates_count": candidates_count,
            "ranked_count": ranked_count,
            "saved_count": saved_count,
            "sheets_saved_count": 0,
            "status": status,
            "error": error,
        }
        return self.upsert_vertex(
            "SearchRun",
            payload,
            f"run_id = '{sql_string(run_id)}'",
        )

    def create_model_run(self, *, run_id: str, model: str, raw_response: str) -> str:
        payload = {
            "run_id": run_id,
            "model": model,
            "raw_response": raw_response,
            "created_at": now_orient(),
        }
        return self.upsert_vertex(
            "ModelRun",
            payload,
            f"run_id = '{sql_string(run_id)}'",
        )

    def create_or_get_news_link(self, link: RankedLink) -> str:
        payload = {
            "url": link.url,
            "title": link.title,
            "source": link.source,
            "source_name": link.source_name,
            "published_at": orient_datetime(link.published_at),
            "domain": link.domain,
            "created_at": orient_datetime(link.created_at),
        }
        existing_rid = self.find_vertex_rid("NewsLink", "url", link.url)
        if existing_rid:
            return existing_rid
        try:
            return self.create_vertex("NewsLink", payload)
        except RuntimeError as exc:
            if "duplicate" not in str(exc).lower():
                raise
            return self.find_vertex_rid("NewsLink", "url", link.url)

    def create_search_result(self, link: RankedLink) -> str:
        result_id = f"{link.run_id}:{link.article_index}"
        payload = {
            "result_id": result_id,
            "run_id": link.run_id,
            "url": link.url,
            "title": link.title,
            "source": link.source,
            "source_name": link.source_name,
            "published_at": orient_datetime(link.published_at),
            "domain": link.domain,
            "query": link.query,
            "rank": link.rank,
            "article_index": link.article_index,
            "llm_score": link.llm_score,
            "reason": link.reason,
            "keywords": ", ".join(link.keywords),
            "created_at": orient_datetime(link.created_at),
        }
        return self.upsert_vertex(
            "SearchResult",
            payload,
            f"result_id = '{sql_string(result_id)}'",
        )

    def create_or_get_source(self, link: RankedLink) -> str:
        name = link.source or link.source_name or "unknown"
        source_key = f"{name.strip().casefold()}|{link.domain.strip().casefold()}"
        return self.upsert_vertex(
            "Source",
            {
                "source_key": source_key,
                "name": name,
                "domain": link.domain,
                "created_at": now_orient(),
            },
            f"source_key = '{sql_string(source_key)}'",
        )

    def update_search_run_status(
        self,
        *,
        run_id: str,
        status: str,
        saved_count: int,
        error: str = "",
        sheets_saved_count: int | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "status": status,
            "saved_count": saved_count,
            "error": error,
            "finished_at": now_orient(),
        }
        if sheets_saved_count is not None:
            payload["sheets_saved_count"] = sheets_saved_count
        self.command(
            "UPDATE SearchRun "
            f"MERGE {json.dumps(payload, ensure_ascii=False)} "
            f"WHERE run_id = '{sql_string(run_id)}'"
        )

    def mark_google_sheets_result(self, *, run_id: str, saved_count: int, error: str = "") -> None:
        status = "success" if not error else "partial"
        self.update_search_run_status(
            run_id=run_id,
            status=status,
            saved_count=self.search_run_saved_count(run_id),
            sheets_saved_count=saved_count,
            error=error,
        )

    def search_run_saved_count(self, run_id: str) -> int:
        response = self.command(
            f"SELECT saved_count FROM SearchRun WHERE run_id = '{sql_string(run_id)}' LIMIT 1"
        )
        result = response.get("result", [])
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return int(result[0].get("saved_count") or 0)
        return 0

    def create_or_get_vertex(self, class_name: str, payload: dict[str, object]) -> str:
        validate_class_name(class_name)
        name = str(payload.get("name") or "").strip()
        if name:
            existing_rid = self.find_vertex_rid(class_name, "name", name)
            if existing_rid:
                return existing_rid
        if name:
            return self.upsert_vertex(
                class_name,
                {**payload, "created_at": now_orient()},
                f"name = '{sql_string(name)}'",
            )
        return self.create_vertex(class_name, {**payload, "created_at": now_orient()})

    def create_vertex(self, class_name: str, payload: dict[str, object]) -> str:
        validate_class_name(class_name)
        response = self.command(
            f"CREATE VERTEX {class_name} CONTENT {json.dumps(payload, ensure_ascii=False)}"
        )
        return extract_first_rid(response)

    def upsert_vertex(
        self,
        class_name: str,
        payload: dict[str, object],
        where_clause: str,
    ) -> str:
        validate_class_name(class_name)
        response = self.command(
            f"UPDATE {class_name} MERGE {json.dumps(payload, ensure_ascii=False)} "
            f"UPSERT RETURN AFTER WHERE {where_clause}"
        )
        return extract_first_rid(response)

    def save_graph_document(
        self,
        *,
        graph_id: str,
        title: str,
        source_type: str,
        nodes: list[dict[str, object]],
        edges: list[dict[str, object]],
    ) -> str:
        self.remove_stale_graph_elements(
            graph_id=graph_id,
            node_ids={str(node["id"]) for node in nodes},
            edge_ids={str(edge["id"]) for edge in edges},
        )
        graph_rid = self.upsert_vertex(
            "GraphDocument",
            {
                "graph_id": graph_id,
                "title": title,
                "source_type": source_type,
                "created_at": now_orient(),
                "updated_at": now_orient(),
            },
            f"graph_id = '{sql_string(graph_id)}'",
        )
        node_rids: dict[str, str] = {}
        for node in nodes:
            node_id = str(node["id"])
            position_3d = node.get("position3d")
            if not isinstance(position_3d, dict):
                position_3d = {}
            node_rids[node_id] = self.upsert_vertex(
                "GraphNode",
                {
                    "graph_id": graph_id,
                    "node_id": node_id,
                    "label": str(node.get("label") or node_id),
                    "node_type": str(node.get("type") or "process"),
                    "shape": str(node.get("shape") or "rounded_rectangle"),
                    "created_at": orient_datetime(str(node.get("created_at") or ""))
                    or now_orient(),
                    "ended_at": orient_datetime(str(node.get("ended_at") or "")),
                    "updated_at": now_orient(),
                    "position_x": int(node.get("x") or 0),
                    "position_y": int(node.get("y") or 0),
                    "position_3d_x": finite_number_or_zero(position_3d.get("x")),
                    "position_3d_y": finite_number_or_zero(position_3d.get("y")),
                    "position_3d_z": finite_number_or_zero(position_3d.get("z")),
                    "image_data": str(node.get("image_data") or ""),
                    "properties_json": json.dumps(
                        node.get("properties") if isinstance(node.get("properties"), list) else [],
                        ensure_ascii=False,
                    ),
                },
                f"graph_id = '{sql_string(graph_id)}' AND node_id = '{sql_string(node_id)}'",
            )
        for edge in edges:
            edge_id = str(edge["id"])
            source_id = str(edge["source"])
            target_id = str(edge["target"])
            source_rid = node_rids.get(source_id)
            target_rid = node_rids.get(target_id)
            if not source_rid or not target_rid:
                raise ValueError(f"Ребро {edge_id} ссылается на отсутствующий узел.")
            existing = self.find_graph_connection_rid(graph_id=graph_id, edge_id=edge_id)
            payload = {
                "graph_id": graph_id,
                "edge_id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": str(edge.get("type") or "follow"),
                "label": str(edge.get("label") or ""),
                "properties_json": json.dumps(
                    edge.get("properties") if isinstance(edge.get("properties"), list) else [],
                    ensure_ascii=False,
                ),
                "created_at": now_orient(),
                "updated_at": now_orient(),
            }
            if existing:
                self.command(f"DELETE EDGE {existing}")
            self.command(
                "CREATE EDGE GraphConnection "
                f"FROM {source_rid} TO {target_rid} "
                f"CONTENT {json.dumps(payload, ensure_ascii=False)}"
            )
        return graph_rid

    def remove_stale_graph_elements(
        self,
        *,
        graph_id: str,
        node_ids: set[str],
        edge_ids: set[str],
    ) -> None:
        escaped_graph_id = sql_string(graph_id)
        edge_rows = response_rows(
            self.command(
                "SELECT @rid AS rid, edge_id FROM GraphConnection "
                f"WHERE graph_id = '{escaped_graph_id}'"
            )
        )
        for row in edge_rows:
            rid = str(row.get("rid") or "")
            if rid and str(row.get("edge_id") or "") not in edge_ids:
                self.command(f"DELETE EDGE {rid}")
        node_rows = response_rows(
            self.command(
                f"SELECT @rid AS rid, node_id FROM GraphNode WHERE graph_id = '{escaped_graph_id}'"
            )
        )
        for row in node_rows:
            rid = str(row.get("rid") or "")
            if rid and str(row.get("node_id") or "") not in node_ids:
                self.command(f"DELETE VERTEX {rid}")

    def find_graph_connection_rid(self, *, graph_id: str, edge_id: str) -> str:
        response = self.command(
            "SELECT FROM GraphConnection "
            f"WHERE graph_id = '{sql_string(graph_id)}' "
            f"AND edge_id = '{sql_string(edge_id)}' LIMIT 1"
        )
        return extract_first_rid(response)

    def find_vertex_rid(self, class_name: str, field_name: str, value: str) -> str:
        validate_class_name(class_name)
        validate_class_name(field_name)
        escaped_value = sql_string(value)
        response = self.command(
            f"SELECT FROM {class_name} WHERE {field_name} = '{escaped_value}' LIMIT 1"
        )
        return extract_first_rid(response)

    def create_edge(self, edge_class: str, from_rid: str, to_rid: str) -> None:
        validate_class_name(edge_class)
        if from_rid and to_rid:
            self.command(f"CREATE EDGE {edge_class} FROM {from_rid} TO {to_rid}")

    def count_class(self, class_name: str) -> int:
        response = self.command(f"SELECT count(*) FROM {class_name}")
        result = response.get("result", [])
        if not result:
            return 0
        count = result[0].get("count(*)", 0)
        return int(count)


def extract_first_rid(response: dict[str, object]) -> str:
    result = response_rows(response)
    if result:
        rid = result[0].get("@rid")
        return str(rid or "")
    return ""


def response_rows(response: dict[str, object]) -> list[dict[str, object]]:
    result = response.get("result", [])
    if not isinstance(result, list):
        return []
    return [row for row in result if isinstance(row, dict)]


def finite_number_or_zero(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def sql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def now_orient() -> str:
    return orient_datetime(datetime.now(UTC).isoformat()) or ""


def orient_datetime(value: str) -> str | None:
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        from email.utils import parsedate_to_datetime

        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for raw_line in sql.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        current.append(line)
        if line.endswith(";"):
            statements.append(" ".join(current).rstrip(";").strip())
            current = []
    if current:
        statements.append(" ".join(current).strip())
    return statements


def validate_class_name(class_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", class_name):
        raise ValueError(f"Некорректное имя класса OrientDB: {class_name}")


def decode_json_response(payload: bytes, *, context: str) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{context} вернул невалидный JSON.") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{context} должен вернуть JSON-объект.")
    return value
