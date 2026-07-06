from __future__ import annotations

import json
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
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OrientDB вернул HTTP {exc.code}: {error_body}") from exc

    def ensure_schema(self, schema_path: Path) -> None:
        statements = split_sql_statements(schema_path.read_text(encoding="utf-8"))
        for statement in statements:
            try:
                self.command(statement)
            except RuntimeError as exc:
                message = str(exc)
                if "already exists" in message or "Cannot create property" in message:
                    continue
                raise

    def save_ranked_links(
        self,
        *,
        query: str,
        run_id: str,
        model: str,
        links: list[RankedLink],
        sources_count: int,
        candidates_count: int,
    ) -> list[SavedRecord]:
        run_rid = self.create_search_run(
            run_id=run_id,
            query=query,
            model=model,
            sources_count=sources_count,
            candidates_count=candidates_count,
            ranked_count=len(links),
            saved_count=len(links),
            status="success",
        )
        model_run_rid = self.create_model_run(
            run_id=run_id,
            model=model,
            raw_response=links[0].llm_raw_response if links else "",
        )
        topic_rid = self.create_or_get_vertex("Topic", {"name": query})
        saved: list[SavedRecord] = []
        for link in links:
            news_rid = self.create_or_update_news_link(link)
            source_rid = self.create_or_get_vertex(
                "Source",
                {
                    "name": link.source or link.source_name or "unknown",
                    "domain": link.domain,
                },
            )
            if run_rid and news_rid:
                self.create_edge("Found", run_rid, news_rid)
                self.create_edge("FoundBy", run_rid, news_rid)
            if news_rid and source_rid:
                self.create_edge("FromSource", news_rid, source_rid)
            if news_rid and topic_rid:
                self.create_edge("About", news_rid, topic_rid)
            if news_rid and model_run_rid:
                self.create_edge("AnalyzedBy", news_rid, model_run_rid)
                self.create_edge("AnalyzedAs", news_rid, model_run_rid)
            saved.append(SavedRecord(url=link.url, rid=news_rid))
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
    ) -> str:
        payload = {
            "run_id": run_id,
            "query": query,
            "model": model,
            "started_at": now_orient(),
            "finished_at": now_orient(),
            "sources_count": sources_count,
            "candidates_count": candidates_count,
            "ranked_count": ranked_count,
            "saved_count": saved_count,
            "status": status,
            "error": error,
        }
        return self.create_vertex("SearchRun", payload)

    def create_model_run(self, *, run_id: str, model: str, raw_response: str) -> str:
        payload = {
            "run_id": run_id,
            "model": model,
            "raw_response": raw_response,
            "created_at": now_orient(),
        }
        return self.create_vertex("ModelRun", payload)

    def create_or_update_news_link(self, link: RankedLink) -> str:
        payload = {
            "run_id": link.run_id,
            "url": link.url,
            "title": link.title,
            "source": link.source,
            "source_name": link.source_name,
            "published_at": orient_datetime(link.published_at),
            "domain": link.domain,
            "query": link.query,
            "llm_score": link.llm_score,
            "reason": link.reason,
            "keywords": ", ".join(link.keywords),
            "created_at": orient_datetime(link.created_at),
        }
        existing_rid = self.find_vertex_rid("NewsLink", "url", link.url)
        if existing_rid:
            response = self.command(
                f"UPDATE {existing_rid} MERGE {json.dumps(payload)} RETURN AFTER"
            )
            updated_rid = extract_first_rid(response)
            return updated_rid or existing_rid
        return self.create_vertex("NewsLink", payload)

    def create_or_get_vertex(self, class_name: str, payload: dict[str, object]) -> str:
        validate_class_name(class_name)
        name = str(payload.get("name") or "").strip()
        if name:
            existing_rid = self.find_vertex_rid(class_name, "name", name)
            if existing_rid:
                return existing_rid
        return self.create_vertex(class_name, {**payload, "created_at": now_orient()})

    def create_vertex(self, class_name: str, payload: dict[str, object]) -> str:
        validate_class_name(class_name)
        response = self.command(f"CREATE VERTEX {class_name} CONTENT {json.dumps(payload)}")
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
    result = response.get("result", [])
    if isinstance(result, list) and result:
        rid = result[0].get("@rid") if isinstance(result[0], dict) else None
        return str(rid or "")
    return ""


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
