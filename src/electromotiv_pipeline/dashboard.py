from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from electromotiv_pipeline.orientdb import OrientDBClient

COUNTS = ("SearchRun", "NewsLink", "Source", "ModelRun")
RUN_SQL = (
    "SELECT run_id, model, status, candidates_count, ranked_count, saved_count, finished_at "
    "FROM SearchRun ORDER BY finished_at DESC LIMIT 10"
)
LINK_SQL = (
    "SELECT title, source, source_name, llm_score, keywords, reason, url, "
    "created_at FROM NewsLink ORDER BY created_at DESC LIMIT 20"
)


def run_dashboard(*, client: OrientDBClient, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), handler_for(client))
    print(f"dashboard_url=http://{host}:{port}")
    server.serve_forever()


def handler_for(client: OrientDBClient) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in {"/", "/index.html"}:
                self.send_error(404)
                return
            body = render_dashboard(client).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def render_dashboard(client: OrientDBClient) -> str:
    counts = "".join(counter(name, safe_count(client, name)) for name in COUNTS)
    runs = table(
        ("run", "model", "status", "candidates", "ranked", "saved", "finished"),
        [
            (
                str(row.get("run_id", ""))[:8],
                row.get("model", ""),
                row.get("status", ""),
                row.get("candidates_count", ""),
                row.get("ranked_count", ""),
                row.get("saved_count", ""),
                row.get("finished_at", ""),
            )
            for row in rows(client, RUN_SQL)
        ],
    )
    links = table(
        ("title", "source", "llm_score", "keywords", "reason", "created"),
        [link_row(row) for row in rows(client, LINK_SQL)],
    )
    return PAGE.format(counts=counts, runs=runs, links=links)


def safe_count(client: OrientDBClient, class_name: str) -> int:
    try:
        return client.count_class(class_name)
    except RuntimeError:
        return 0


def rows(client: OrientDBClient, sql: str) -> list[dict[str, object]]:
    try:
        result = client.command(sql).get("result", [])
    except RuntimeError:
        return []
    return [row for row in result if isinstance(row, dict)]


def counter(name: str, value: int) -> str:
    return f'<div class="counter"><b>{value}</b>{escape(name)}</div>'


def table(headers: tuple[str, ...], data: list[tuple[object, ...]]) -> str:
    if not data:
        return "<p>Данных пока нет.</p>"
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(td(cell) for cell in row) + "</tr>" for row in data)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def link_row(row: dict[str, object]) -> tuple[object, ...]:
    title = escape(str(row.get("title", "")))
    url = escape(str(row.get("url", "")))
    source = row.get("source") or row.get("source_name", "")
    return (
        f'<a href="{url}">{title}</a>',
        source,
        row.get("llm_score", ""),
        row.get("keywords", ""),
        row.get("reason", ""),
        row.get("created_at", ""),
    )


def td(value: object) -> str:
    text = str(value)
    return f"<td>{text if '<a ' in text or '<br>' in text else escape(text)}</td>"


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>ElectroMotiv News Pipeline</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color: #111; }}
h1 {{ font-size: 24px; margin-bottom: 16px; }} h2 {{ font-size: 18px; margin-top: 28px; }}
.counts {{ display: flex; gap: 12px; flex-wrap: wrap; }}
.counter {{ border: 1px solid #ddd; border-radius: 6px; padding: 10px 14px; }}
.counter b {{ display: block; font-size: 20px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; font-size: 13px; }}
th {{ background: #f4f4f4; text-align: left; }} a {{ color: #0645ad; }}
</style></head><body>
<h1>ElectroMotiv News Pipeline</h1><div class="counts">{counts}</div>
<h2>Последние запуски</h2>{runs}<h2>Последние новости</h2>{links}
</body></html>"""
